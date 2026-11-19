"""External API credentials and connection values (Administración → APIs).

- Each integration declares its fields; a field is either a secret (an API key) or a plain value (a catalog slug).
- Secrets are encrypted at rest with AES-256-GCM. The key is derived (HKDF-SHA256) from INTEGRATIONS_SECRET_KEY, or
  from SESSION_SECRET when that variable is not set. The ciphertext is bound to its integration and field.
- Secrets never leave the server: the API returns only whether a field is configured, its source and, for secrets,
  the last 4 characters. The audit log records which fields changed, never their values.
- An environment variable can provide each field (Kilby secret env var). A value saved in the panel takes precedence.
- If the encryption key changes (SESSION_SECRET rotated without INTEGRATIONS_SECRET_KEY), stored secrets become
  unreadable: the panel says so and an administrator enters them again. Nothing crashes and nothing is sent.
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import db
from infrastructure import ManagementError, _audit

SCHEMA_VERSION = "v1"


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    secret: bool = False
    pattern: str = r"[^\x00-\x1f]{1,200}"
    env: str = ""
    help: str = ""


@dataclass(frozen=True)
class Integration:
    id: str
    label: str
    description: str
    fields: Tuple[Field, ...]
    docs_url: str = ""


INTEGRATIONS: Dict[str, Integration] = {
    "neuravision": Integration(
        id="neuravision", label="Neuravision (Kilby)",
        description="Análisis de góndolas con Neuravision en Kilby. Sin esta clave el análisis no se ejecuta y Kilby no registra uso.",
        fields=(
            Field("api_key", "Clave de API", secret=True, pattern=r"kai_[A-Za-z0-9_-]{16,196}", env="NEURAVISION_API_KEY",
                  help="La clave que entrega Kilby al activar Neuravision (panel de Kilby → Neuravision → Create key). Empieza con kai_."),
            Field("catalog", "Catálogo", pattern=r"[a-z0-9][a-z0-9-]{0,39}", env="KILBY_NEURAVISION_CATALOG",
                  help="Slug del catálogo en Kilby (por ejemplo salud-sexual). Obligatorio solo si el espacio tiene más de un catálogo."),
            Field("dataset_key", "Clave para catálogo y entrenamientos (opcional)", secret=True, pattern=r"kai_[A-Za-z0-9_-]{16,196}",
                  env="NEURAVISION_DATASET_KEY",
                  help="Clave de Kilby con el permiso «Manage catalogs and trainings» (solo un administrador del espacio de Kilby puede crearla). "
                       "Si se omite, se usa la clave de API, que entonces necesita ese permiso para sincronizar productos y entrenar."),
        ),
        docs_url="https://kilby.neuramorphic.ai/docs/neuravision",
    ),
}

_TESTS: Dict[str, float] = {}
_TEST_LOCK = threading.Lock()
TEST_MIN_INTERVAL_S = 5
GENERATION = {"value": 0}  # bumped on every change, so caches (kilby_model.health) refresh at once


def integration(integration_id: str) -> Integration:
    found = INTEGRATIONS.get(integration_id)
    if found is None:
        raise ManagementError("Integración no encontrada.", 404)
    return found


def _field(item: Integration, name: str) -> Field:
    for candidate in item.fields:
        if candidate.name == name:
            return candidate
    raise ManagementError("Campo de integración no encontrado.", 404)


# ---------------------------------------------------------------------------- encryption

def _key() -> Tuple[bytes, str]:
    raw = os.environ.get("INTEGRATIONS_SECRET_KEY") or os.environ.get("SESSION_SECRET") or ""
    if len(raw) < 16:
        raise ManagementError("El servidor no tiene una clave de cifrado para las APIs (INTEGRATIONS_SECRET_KEY o SESSION_SECRET).", 503)
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"salcobrand-integrations",
               info=b"integration-secrets/" + SCHEMA_VERSION.encode()).derive(raw.encode())
    return key, hashlib.sha256(b"key-id:" + key).hexdigest()[:12]


def _encrypt(integration_id: str, field: str, value: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key, key_id = _key()
    nonce = os.urandom(12)
    sealed = AESGCM(key).encrypt(nonce, value.encode(), f"{integration_id}/{field}".encode())
    return {"ct": SCHEMA_VERSION + ":" + base64.b64encode(nonce + sealed).decode(), "kid": key_id, "last4": value[-4:]}


def _decrypt(integration_id: str, field: str, entry: dict) -> Optional[str]:
    """None when the value cannot be read with the current key (rotated) or was tampered with."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        key, key_id = _key()
        version, payload = str(entry.get("ct", "")).split(":", 1)
        if version != SCHEMA_VERSION or entry.get("kid") != key_id:
            return None
        blob = base64.b64decode(payload, validate=True)
        return AESGCM(key).decrypt(blob[:12], blob[12:], f"{integration_id}/{field}".encode()).decode()
    except (ValueError, InvalidTag, ManagementError):
        return None


# ---------------------------------------------------------------------------- storage

def _row(conn, integration_id: str, lock: bool = False) -> dict:
    conn.execute("INSERT INTO management_integrations (id, values_json, secrets_json, version) VALUES (?, '{}', '{}', 0) "
                 "ON CONFLICT DO NOTHING", (integration_id,))
    suffix = " FOR UPDATE" if lock and db.USE_PG else ""
    row = conn.execute("SELECT * FROM management_integrations WHERE id = ?" + suffix, (integration_id,)).fetchone()
    return {"values": json.loads(row["values_json"] or "{}"), "secrets": json.loads(row["secrets_json"] or "{}"),
            "test": json.loads(row["test_json"]) if row["test_json"] else None, "version": row["version"],
            "updated_by": row["updated_by"], "updated_at": row["updated_at"]}


def _load(integration_id: str) -> dict:
    with db.get_conn() as conn:
        return _row(conn, integration_id)


def secret(integration_id: str, field: str) -> Optional[str]:
    """The secret for server-side use: the panel's value, else its environment variable, else None."""
    item = integration(integration_id)
    spec = _field(item, field)
    entry = _load(integration_id)["secrets"].get(field)
    if entry:
        value = _decrypt(integration_id, field, entry)
        if value:
            return value
    env = os.environ.get(spec.env, "").strip() if spec.env else ""
    return env or None


def value(integration_id: str, field: str) -> Optional[str]:
    item = integration(integration_id)
    spec = _field(item, field)
    stored = _load(integration_id)["values"].get(field)
    if stored:
        return stored
    env = os.environ.get(spec.env, "").strip() if spec.env else ""
    return env or None


def field_states(integration_id: str, state: dict = None) -> list:
    item = integration(integration_id)
    state = state or _load(integration_id)
    result = []
    for spec in item.fields:
        env_set = bool(spec.env and os.environ.get(spec.env, "").strip())
        out = {"name": spec.name, "label": spec.label, "secret": spec.secret, "help": spec.help, "env": spec.env or None}
        if spec.secret:
            entry = state["secrets"].get(spec.name)
            readable = bool(entry) and _decrypt(integration_id, spec.name, entry) is not None
            out.update({"configured": readable or env_set, "unreadable": bool(entry) and not readable,
                        "source": "panel" if readable else ("entorno" if env_set else None),
                        "last4": entry.get("last4") if readable else None})
        else:
            stored = state["values"].get(spec.name)
            out.update({"configured": bool(stored) or env_set, "unreadable": False,
                        "source": "panel" if stored else ("entorno" if env_set else None),
                        "value": stored or (os.environ.get(spec.env, "").strip() if env_set else None)})
        result.append(out)
    return result


def overview(can_edit: bool) -> dict:
    items = []
    for item in INTEGRATIONS.values():
        state = _load(item.id)
        items.append({"id": item.id, "label": item.label, "description": item.description, "docs_url": item.docs_url,
                      "fields": field_states(item.id, state), "version": state["version"], "updated_by": state["updated_by"],
                      "updated_at": state["updated_at"], "test": state["test"]})
    return {"integrations": items, "can_edit": can_edit}


def _clean(spec: Field, raw) -> str:
    if not isinstance(raw, str):
        raise ManagementError(spec.label + ": ingresa un texto.")
    text = raw.strip()
    if not re.fullmatch(spec.pattern, text):
        if spec.secret:
            raise ManagementError(spec.label + ": el formato no es válido. " + spec.help)
        raise ManagementError(spec.label + ": el valor no es válido. " + spec.help)
    return text


def save(integration_id: str, values: dict, version: int, actor: str, remove: tuple = ()) -> dict:
    """Sets the given fields (secrets encrypted) and removes the fields in `remove`. Optimistic lock on `version`."""
    item = integration(integration_id)
    if not isinstance(values, dict) or (not values and not remove):
        raise ManagementError("Indica al menos un valor para guardar.")
    specs = {spec.name: spec for spec in item.fields}
    unknown = (set(values) | set(remove)) - set(specs)
    if unknown:
        raise ManagementError("Campo de integración no encontrado.", 404)
    cleaned = {name: _clean(specs[name], raw) for name, raw in values.items()}
    with db.get_conn() as conn:
        current = _row(conn, integration_id, lock=True)
        if type(version) is not int or version != current["version"]:
            raise ManagementError("La configuración de APIs cambió en otra sesión. Recarga antes de guardar.", 409)
        before = {spec["name"]: spec["configured"] for spec in field_states(integration_id, current)}
        secrets, plain = dict(current["secrets"]), dict(current["values"])
        for name, text in cleaned.items():
            if specs[name].secret:
                secrets[name] = _encrypt(integration_id, name, text)
            else:
                plain[name] = text
        for name in remove:
            secrets.pop(name, None)
            plain.pop(name, None)
        reset_test = any(specs[name].secret for name in (*cleaned, *remove))
        conn.execute("UPDATE management_integrations SET values_json = ?, secrets_json = ?, version = version + 1, updated_by = ?, "
                     "updated_at = ?" + (", test_json = NULL" if reset_test else "") + " WHERE id = ?",
                     (json.dumps(plain), json.dumps(secrets), actor, db.now_iso(), integration_id))
        after_state = _row(conn, integration_id)
        after = {spec["name"]: spec["configured"] for spec in field_states(integration_id, after_state)}
        _audit(conn, actor, "integration.update", integration_id, {"configured": before},
               {"configured": after, "changed": sorted(cleaned), "removed": sorted(remove)})
    GENERATION["value"] += 1
    return overview_one(integration_id)


def overview_one(integration_id: str) -> dict:
    item = integration(integration_id)
    state = _load(integration_id)
    return {"id": item.id, "label": item.label, "description": item.description, "docs_url": item.docs_url,
            "fields": field_states(integration_id, state), "version": state["version"], "updated_by": state["updated_by"],
            "updated_at": state["updated_at"], "test": state["test"]}


def test(integration_id: str, actor: str, candidate: Optional[dict] = None) -> dict:
    """Probar conexión. With `candidate` it tests unsaved values (nothing is stored); otherwise the saved ones, and the
    result is kept so viewers see it. At most one test every few seconds per integration."""
    item = integration(integration_id)
    with _TEST_LOCK:
        last = _TESTS.get(integration_id)
        if last is not None and time.monotonic() - last < TEST_MIN_INTERVAL_S:
            raise ManagementError("Espera unos segundos antes de volver a probar la conexión.", 429)
        _TESTS[integration_id] = time.monotonic()
    specs = {spec.name: spec for spec in item.fields}
    if candidate:
        unknown = set(candidate) - set(specs)
        if unknown:
            raise ManagementError("Campo de integración no encontrado.", 404)
        given = {name: _clean(specs[name], raw) for name, raw in candidate.items()}
    else:
        given = {}
    if integration_id == "neuravision":
        import kilby_model
        key = given.get("api_key") or secret(integration_id, "api_key")
        if not key:
            result = {"ok": False, "code": "missing_key", "message": kilby_model.kn.message_es("missing_key")}
        else:
            result = kilby_model.check_connection(key)
    else:  # pragma: no cover - every integration declares its test here
        raise ManagementError("Esta integración no tiene prueba de conexión.", 404)
    result = {**result, "at": db.now_iso(), "by": actor, "candidate": bool(candidate)}
    if not candidate:
        with db.get_conn() as conn:
            _row(conn, integration_id)
            conn.execute("UPDATE management_integrations SET test_json = ? WHERE id = ?", (json.dumps(result), integration_id))
        GENERATION["value"] += 1
    return result
