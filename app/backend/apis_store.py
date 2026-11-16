"""Tienda de la API v1: llaves, cuotas y telemetría (SPEC §2–4 y §8 de apis-portal/SPEC.md).

Dos backends con los mismos métodos, elegidos por APIS_STORE:
  - dynamodb (producción): tabla single-table `neuramorphic-apis` (env APIS_TABLE), compartida con el portal.
  - memory (pruebas locales sin AWS): dict en memoria con la misma forma de ítems (pk/sk).

Reglas: la resolución de llaves puede lanzar (el caller responde 401); las escrituras de telemetría NUNCA lanzan
(se registran en el log y se sigue). Las cuotas fallan "abiertas" si DynamoDB no responde.
"""
import hashlib
import os
import secrets
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

TABLE_DEFAULT = "neuramorphic-apis"
KEY_CACHE_TTL_S = 60          # SPEC §3: caché en memoria 60 s
EVENT_TTL_DAYS = 180          # SPEC §2: eventos viven 180 días
MINUTE_TTL_S = 10 * 60        # cuota del minuto: ttl +10 min
DAY_TTL_S = 3 * 24 * 3600     # cuota del día: ttl +3 días
TOUCH_INTERVAL_S = 60         # last_used_at se escribe a lo más una vez por minuto por llave
# (llamadas/min, fotos/día) por plan cuando el cliente no trae cuotas explícitas (SPEC §3: pilot = 60 / 400)
PLAN_DEFAULTS = {"pilot": (60, 400), "standard": (120, 2000), "enterprise": (600, 20000)}


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_ms(dt: datetime) -> str:
    """ISO-8601 UTC con milisegundos y sufijo Z (formato de `ts` y del sk de los eventos)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso_ms(utc_now())


def sha256_hex(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def key_prefix(raw_key: str) -> str:
    return raw_key[:12]


def new_raw_key(client_id: str) -> str:
    """Formato SPEC §3: nv_<client_id>_<token_urlsafe(32)>."""
    return f"nv_{client_id}_{secrets.token_urlsafe(32)}"


def minute_bucket(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def day_bucket(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def seconds_to_next_minute(dt: datetime) -> int:
    return max(1, 60 - dt.second)


def seconds_to_next_day(dt: datetime) -> int:
    nxt = (dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((nxt - dt).total_seconds()))


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def plain(obj: Any) -> Any:
    """Decimal (DynamoDB) → int/float, recursivo."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [plain(v) for v in obj]
    return obj


def dynamo_safe(obj: Any) -> Any:
    """float → Decimal (DynamoDB no acepta float), recursivo."""
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: dynamo_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [dynamo_safe(v) for v in obj]
    return obj


def _log(msg: str) -> None:
    print(f"[apis-store] {msg}", flush=True)


# ---------------------------------------------------------------------------
# lógica común (sobre primitivas get/put/update/query de cada backend)
# ---------------------------------------------------------------------------

class BaseStore:
    name = "base"

    def __init__(self):
        self._cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._touched: Dict[Tuple[str, str], float] = {}
        self._ensured = set()          # (pk, sk, mapa[, clave]) cuya existencia ya garantizamos (ahorra UpdateItems)
        self._max_seen: Dict[Tuple[str, str], int] = {}

    # --- primitivas que implementa cada backend ---------------------------------------------------
    def _get_item(self, pk: str, sk: str) -> Optional[dict]:
        raise NotImplementedError

    def _put_item(self, item: dict) -> None:
        raise NotImplementedError

    def _update_counters(self, pk: str, sk: str, adds: Dict[str, int], sets: Dict[str, Any] = None,
                         set_if_absent: Dict[str, Any] = None) -> dict:
        """ADD numéricos + SET (+ SET if_not_exists). Devuelve el ítem resultante (valores planos)."""
        raise NotImplementedError

    def _add_nested(self, pk: str, sk: str, map_attr: str, map_key: str, adds) -> None:
        """ADD dentro de un mapa: adds es int (mapa → número) o dict (mapa → {campo: número})."""
        raise NotImplementedError

    def _set_max(self, pk: str, sk: str, attr: str, value: int) -> None:
        raise NotImplementedError

    def _set_fields(self, pk: str, sk: str, fields: Dict[str, Any]) -> None:
        raise NotImplementedError

    def _query(self, pk: str, sk_from: str, sk_to: str) -> List[dict]:
        raise NotImplementedError

    # --- caché 60 s ----------------------------------------------------------------------------------
    def _cached(self, key: Tuple[str, str], loader):
        now = time.monotonic()
        with self._lock:
            ent = self._cache.get(key)
            if ent and ent[0] > now:
                return ent[1]
        value = loader()
        with self._lock:
            if len(self._cache) > 5000:
                self._cache.clear()
            self._cache[key] = (now + KEY_CACHE_TTL_S, value)
        return value

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self._ensured.clear()
            self._max_seen.clear()
            self._touched.clear()

    # --- clientes y llaves ---------------------------------------------------------------------------
    def get_client(self, client_id: str) -> Optional[dict]:
        return self._cached(("client", client_id), lambda: self._get_item(f"client#{client_id}", "meta"))

    def _load_key_context(self, client_id: Optional[str], key_id: Optional[str]) -> Optional[dict]:
        if not client_id or not key_id:
            return None
        client = self._get_item(f"client#{client_id}", "meta")
        key = self._get_item(f"client#{client_id}", f"key#{key_id}")
        if not client or not key:
            return None
        return {"client": client, "key": key}

    def _lookup_by_hash(self, key_hash: str) -> Optional[dict]:
        idx = self._get_item(f"key#{key_hash}", "meta")
        if not idx:
            return None
        return self._load_key_context(idx.get("client_id"), idx.get("key_id"))

    def _lookup_by_apigw(self, apigw_key_id: str) -> Optional[dict]:
        idx = self._get_item(f"apigwkey#{apigw_key_id}", "meta")
        if not idx:
            return None
        return self._load_key_context(idx.get("client_id"), idx.get("key_id"))

    @staticmethod
    def _validate(ctx: Optional[dict]) -> Optional[dict]:
        """Estado/vencimiento se evalúan en cada llamada (la caché guarda los ítems crudos)."""
        if not ctx:
            return None
        key, client = ctx.get("key"), ctx.get("client")
        if not key or not client:
            return None
        if (key.get("status") or "active") != "active":
            return None
        exp = parse_iso(key.get("expires_at"))
        if exp is not None and exp <= utc_now():
            return None
        return {"client": plain(dict(client)), "key": plain(dict(key))}

    def resolve_key(self, raw_key: Optional[str]) -> Optional[dict]:
        """sha256(llave) → key#<hash> → client#…/meta + client#…/key#…  → {client, key} | None.
        Devuelve el contexto aunque el cliente esté suspendido (el caller responde 403)."""
        raw_key = (raw_key or "").strip()
        if not raw_key or len(raw_key) > 200:
            return None
        h = sha256_hex(raw_key)
        return self._validate(self._cached(("hash", h), lambda: self._lookup_by_hash(h)))

    def resolve_apigw_key_id(self, apigw_key_id: Optional[str]) -> Optional[dict]:
        """Identidad que manda API Gateway (SPEC §8): apigwkey#<apiKeyId> → {client_id, key_id}."""
        apigw_key_id = (apigw_key_id or "").strip()
        if not apigw_key_id or len(apigw_key_id) > 100:
            return None
        return self._validate(self._cached(("apigw", apigw_key_id), lambda: self._lookup_by_apigw(apigw_key_id)))

    # --- cuotas --------------------------------------------------------------------------------------
    @staticmethod
    def quotas_for(client: Optional[dict]) -> Tuple[int, int]:
        """(llamadas/min, fotos/día); 0 = sin límite."""
        plan = (client or {}).get("plan") or "pilot"
        d_calls, d_photos = PLAN_DEFAULTS.get(plan, PLAN_DEFAULTS["pilot"])
        calls = (client or {}).get("quota_calls_min")
        photos = (client or {}).get("quota_photos_day")
        return int(calls if calls is not None else d_calls), int(photos if photos is not None else d_photos)

    def check_and_count_quota(self, client_id: str, photos: int = 0, calls: int = 1, client: dict = None) -> Tuple[bool, int]:
        """Suma `calls` al minuto y `photos` al día (UpdateItem ADD + ttl) y compara con las cuotas del cliente.
        Devuelve (ok, retry_after_s). Si la tienda falla, deja pasar (y lo registra)."""
        try:
            client = client or self.get_client(client_id) or {}
            limit_calls, limit_photos = self.quotas_for(client)
            now = utc_now()
            epoch = int(time.time())
            if calls:
                item = self._update_counters(f"quota#{client_id}", f"min#{minute_bucket(now)}", {"calls": int(calls)},
                                             set_if_absent={"ttl": epoch + MINUTE_TTL_S, "client_id": client_id})
                if limit_calls and int(item.get("calls") or 0) > limit_calls:
                    return False, seconds_to_next_minute(now)
            if photos:
                item = self._update_counters(f"quota#{client_id}", f"day#{day_bucket(now)}", {"photos": int(photos)},
                                             set_if_absent={"ttl": epoch + DAY_TTL_S, "client_id": client_id})
                if limit_photos and int(item.get("photos") or 0) > limit_photos:
                    # la llamada se rechaza: devolver las fotos al contador para no castigar la siguiente
                    self._update_counters(f"quota#{client_id}", f"day#{day_bucket(now)}", {"photos": -int(photos)})
                    return False, seconds_to_next_day(now)
            return True, 0
        except Exception as exc:
            _log(f"cuota no verificable ({type(exc).__name__}: {exc}); se deja pasar")
            return True, 0

    def quota_snapshot(self, client_id: str) -> dict:
        now = utc_now()
        m = self._get_item(f"quota#{client_id}", f"min#{minute_bucket(now)}") or {}
        d = self._get_item(f"quota#{client_id}", f"day#{day_bucket(now)}") or {}
        return {"minute": minute_bucket(now), "calls_this_minute": int(plain(m.get("calls") or 0)),
                "day": day_bucket(now), "photos_today": int(plain(d.get("photos") or 0))}

    # --- telemetría (nunca lanza) --------------------------------------------------------------------
    def record_event(self, evt: dict) -> None:
        try:
            item = dict(evt)
            item.setdefault("pk", f"evt#{evt['client_id']}")
            item.setdefault("sk", f"{evt['ts']}#{evt['request_id']}")
            item.setdefault("ttl", int(time.time()) + EVENT_TTL_DAYS * 86400)
            self._put_item(item)
        except Exception as exc:
            _log(f"record_event falló: {type(exc).__name__}: {exc}")

    def update_event(self, client_id: str, sk: str, fields: dict) -> None:
        """Completa el evento de la llamada POST /v1/analyze cuando el job termina (lectura, caras, ms del motor)."""
        try:
            if not sk:
                return
            self._set_fields(f"evt#{client_id}", sk, fields)
        except Exception as exc:
            _log(f"update_event falló: {type(exc).__name__}: {exc}")

    def add_aggregates(self, client_id: str, day: str, evt: dict, call: bool = True) -> None:
        """agg#<client>/day#<day>: con call=True suma calls/errors/photos/latencia + by_endpoint + by_key;
        facings/needs_review se suman cuando vienen (lo hace el job al terminar) y jobs_failed si el job falló."""
        try:
            pk, sk = f"agg#{client_id}", f"day#{day}"
            status = int(evt.get("status") or 0)
            is_err = status >= 400 or bool(evt.get("error"))
            latency = int(evt.get("latency_ms") or 0)
            adds: Dict[str, int] = {}
            if call:
                adds["calls"] = 1
                if is_err:
                    adds["errors"] = 1
                if evt.get("photos"):
                    adds["photos"] = int(evt["photos"])
                adds["latency_ms_sum"] = latency
            for f in ("facings", "needs_review"):
                if evt.get(f) is not None:
                    adds[f] = int(evt[f])
            if evt.get("job_failed"):
                adds["jobs_failed"] = 1
            if not adds:
                return
            now = now_iso()
            self._update_counters(pk, sk, adds, sets={"updated_at": now},
                                  set_if_absent={"client_id": client_id, "day": day, "created_at": now})
            if call:
                endpoint = evt.get("endpoint") or "?"
                self._add_nested(pk, sk, "by_endpoint", endpoint, {"calls": 1, "errors": 1 if is_err else 0, "latency_ms_sum": latency})
                if evt.get("key_id"):
                    self._add_nested(pk, sk, "by_key", evt["key_id"], 1)
                if latency > self._max_seen.get((pk, sk), -1):
                    self._set_max(pk, sk, "latency_ms_max", latency)
                    self._max_seen[(pk, sk)] = latency
        except Exception as exc:
            _log(f"add_aggregates falló: {type(exc).__name__}: {exc}")

    def touch_key_last_used(self, client_id: str, key_id: str) -> None:
        try:
            now = time.monotonic()
            with self._lock:
                last = self._touched.get((client_id, key_id))
                if last is not None and now - last < TOUCH_INTERVAL_S:
                    return
                self._touched[(client_id, key_id)] = now
            self._set_fields(f"client#{client_id}", f"key#{key_id}", {"last_used_at": now_iso()})
        except Exception as exc:
            _log(f"touch_key_last_used falló: {type(exc).__name__}: {exc}")

    def usage(self, client_id: str, from_day: str, to_day: str) -> List[dict]:
        """Agregados diarios (lee agg#<client>/day#…). Puede lanzar (el caller responde 503)."""
        out = []
        for item in self._query(f"agg#{client_id}", f"day#{from_day}", f"day#{to_day}"):
            d = plain(dict(item))
            d["day"] = d.get("day") or str(d.get("sk", ""))[4:]
            d.pop("pk", None)
            d.pop("sk", None)
            calls = int(d.get("calls") or 0)
            d["latency_ms_avg"] = round(int(d.get("latency_ms_sum") or 0) / calls) if calls else None
            out.append(d)
        out.sort(key=lambda x: x["day"])
        return out


# ---------------------------------------------------------------------------
# backend en memoria (pruebas locales; APIS_STORE=memory)
# ---------------------------------------------------------------------------

class MemoryStore(BaseStore):
    name = "memory"

    def __init__(self):
        super().__init__()
        self.items: Dict[Tuple[str, str], dict] = {}
        self._ilock = threading.RLock()

    # primitivas
    def _get_item(self, pk, sk):
        with self._ilock:
            it = self.items.get((pk, sk))
            return dict(it) if it else None

    def _put_item(self, item):
        with self._ilock:
            self.items[(item["pk"], item["sk"])] = dict(item)

    def _item(self, pk, sk) -> dict:
        it = self.items.get((pk, sk))
        if it is None:
            it = {"pk": pk, "sk": sk}
            self.items[(pk, sk)] = it
        return it

    def _update_counters(self, pk, sk, adds, sets=None, set_if_absent=None):
        with self._ilock:
            it = self._item(pk, sk)
            for k, v in (adds or {}).items():
                it[k] = (it.get(k) or 0) + v
            for k, v in (sets or {}).items():
                it[k] = v
            for k, v in (set_if_absent or {}).items():
                it.setdefault(k, v)
            return dict(it)

    def _add_nested(self, pk, sk, map_attr, map_key, adds):
        with self._ilock:
            it = self._item(pk, sk)
            m = it.setdefault(map_attr, {})
            if isinstance(adds, dict):
                entry = m.setdefault(map_key, {})
                for k, v in adds.items():
                    entry[k] = (entry.get(k) or 0) + v
            else:
                m[map_key] = (m.get(map_key) or 0) + adds

    def _set_max(self, pk, sk, attr, value):
        with self._ilock:
            it = self._item(pk, sk)
            if it.get(attr) is None or it[attr] < value:
                it[attr] = value

    def _set_fields(self, pk, sk, fields):
        with self._ilock:
            self._item(pk, sk).update(fields)

    def _query(self, pk, sk_from, sk_to):
        with self._ilock:
            return [dict(v) for (p, s), v in self.items.items() if p == pk and sk_from <= s <= sk_to]

    # ayudas para pruebas / desarrollo local
    @property
    def events(self) -> List[dict]:
        with self._ilock:
            return sorted((dict(v) for (p, _s), v in self.items.items() if p.startswith("evt#")), key=lambda e: e["sk"])

    def seed_client(self, client_id: str = "salcobrand", name: str = None, plan: str = "pilot", status: str = "active",
                    quota_calls_min: int = None, quota_photos_day: int = None, contact_email: str = None) -> dict:
        d_calls, d_photos = PLAN_DEFAULTS.get(plan, PLAN_DEFAULTS["pilot"])
        item = {"pk": f"client#{client_id}", "sk": "meta", "client_id": client_id, "name": name or client_id.title(),
                "contact_email": contact_email, "status": status, "plan": plan,
                "quota_photos_day": d_photos if quota_photos_day is None else quota_photos_day,
                "quota_calls_min": d_calls if quota_calls_min is None else quota_calls_min,
                "notes": "", "created_by": "memory", "created_at": now_iso(), "updated_at": now_iso()}
        self._put_item(item)
        self.clear_cache()
        return item

    def seed_key(self, client_id: str, raw_key: str = None, label: str = "demo", expires_at: str = None,
                 apigw_key_id: str = None) -> str:
        raw_key = raw_key or new_raw_key(client_id)
        key_id = secrets.token_hex(4)
        h = sha256_hex(raw_key)
        self._put_item({"pk": f"client#{client_id}", "sk": f"key#{key_id}", "key_id": key_id, "key_prefix": key_prefix(raw_key),
                        "key_hash": h, "label": label, "status": "active", "expires_at": expires_at, "last_used_at": None,
                        "created_by": "memory", "created_at": now_iso(), "revoked_at": None, "revoked_by": None,
                        "apigw_key_id": apigw_key_id})
        self._put_item({"pk": f"key#{h}", "sk": "meta", "client_id": client_id, "key_id": key_id, "status": "active",
                        "expires_at": expires_at, "apigw_key_id": apigw_key_id})
        if apigw_key_id:
            self._put_item({"pk": f"apigwkey#{apigw_key_id}", "sk": "meta", "client_id": client_id, "key_id": key_id})
        self.clear_cache()
        return raw_key

    def seed_demo_key(self, client_id: str = "salcobrand", apigw_key_id: str = None, **client_kwargs) -> str:
        """Cliente + llave listos para probar; devuelve la llave en claro."""
        if self._get_item(f"client#{client_id}", "meta") is None or client_kwargs:
            self.seed_client(client_id, **client_kwargs)
        return self.seed_key(client_id, apigw_key_id=apigw_key_id)

    def revoke_key(self, client_id: str, key_id: str) -> None:
        with self._ilock:
            key = self.items.get((f"client#{client_id}", f"key#{key_id}"))
            if key:
                key.update({"status": "revoked", "revoked_at": now_iso()})
                idx = self.items.get((f"key#{key['key_hash']}", "meta"))
                if idx:
                    idx["status"] = "revoked"
        self.clear_cache()

    def set_client_status(self, client_id: str, status: str) -> None:
        self._set_fields(f"client#{client_id}", "meta", {"status": status, "updated_at": now_iso()})
        self.clear_cache()


# ---------------------------------------------------------------------------
# backend DynamoDB (producción)
# ---------------------------------------------------------------------------

class DynamoStore(BaseStore):
    name = "dynamodb"

    def __init__(self, table_name: str = TABLE_DEFAULT, region: str = None):
        super().__init__()
        self.table_name = table_name
        self.region = region or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
        self._table = None
        self._tlock = threading.Lock()

    @property
    def table(self):
        if self._table is None:
            with self._tlock:
                if self._table is None:
                    import boto3

                    self._table = boto3.resource("dynamodb", region_name=self.region).Table(self.table_name)
        return self._table

    @staticmethod
    def _is_condition_failed(exc) -> bool:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        return code == "ConditionalCheckFailedException"

    def _get_item(self, pk, sk):
        resp = self.table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=False)
        item = resp.get("Item")
        return plain(item) if item else None

    def _put_item(self, item):
        self.table.put_item(Item=dynamo_safe(item))

    def _update_counters(self, pk, sk, adds, sets=None, set_if_absent=None):
        names, values, add_parts, set_parts = {}, {}, [], []
        i = 0
        for k, v in (adds or {}).items():
            names[f"#a{i}"] = k
            values[f":a{i}"] = int(v)
            add_parts.append(f"#a{i} :a{i}")
            i += 1
        for k, v in (sets or {}).items():
            names[f"#s{i}"] = k
            values[f":s{i}"] = dynamo_safe(v)
            set_parts.append(f"#s{i} = :s{i}")
            i += 1
        for k, v in (set_if_absent or {}).items():
            names[f"#n{i}"] = k
            values[f":n{i}"] = dynamo_safe(v)
            set_parts.append(f"#n{i} = if_not_exists(#n{i}, :n{i})")
            i += 1
        expr = ("ADD " + ", ".join(add_parts)) if add_parts else ""
        if set_parts:
            expr += (" " if expr else "") + "SET " + ", ".join(set_parts)
        resp = self.table.update_item(Key={"pk": pk, "sk": sk}, UpdateExpression=expr, ExpressionAttributeNames=names,
                                      ExpressionAttributeValues=values, ReturnValues="ALL_NEW")
        return plain(resp.get("Attributes") or {})

    def _add_nested(self, pk, sk, map_attr, map_key, adds):
        key = {"pk": pk, "sk": sk}
        # DynamoDB no permite ADD en una ruta cuyo mapa padre no existe, ni SET y ADD sobre rutas solapadas en
        # el mismo UpdateItem: se garantiza el mapa (y la entrada) con if_not_exists y luego se suma. Se recuerda
        # por proceso qué mapas ya existen para que, en régimen, sea un único UpdateItem por llamada.
        if (pk, sk, map_attr) not in self._ensured:
            self.table.update_item(Key=key, UpdateExpression="SET #m = if_not_exists(#m, :empty)",
                                   ExpressionAttributeNames={"#m": map_attr}, ExpressionAttributeValues={":empty": {}})
            self._ensured.add((pk, sk, map_attr))
        if isinstance(adds, dict):
            if (pk, sk, map_attr, map_key) not in self._ensured:
                self.table.update_item(Key=key, UpdateExpression="SET #m.#k = if_not_exists(#m.#k, :empty)",
                                       ExpressionAttributeNames={"#m": map_attr, "#k": map_key},
                                       ExpressionAttributeValues={":empty": {}})
                self._ensured.add((pk, sk, map_attr, map_key))
            names, values, parts = {"#m": map_attr, "#k": map_key}, {}, []
            for i, (f, v) in enumerate(adds.items()):
                names[f"#f{i}"] = f
                values[f":v{i}"] = int(v)
                parts.append(f"#m.#k.#f{i} :v{i}")
            self.table.update_item(Key=key, UpdateExpression="ADD " + ", ".join(parts), ExpressionAttributeNames=names,
                                   ExpressionAttributeValues=values)
        else:
            self.table.update_item(Key=key, UpdateExpression="ADD #m.#k :v", ExpressionAttributeNames={"#m": map_attr, "#k": map_key},
                                   ExpressionAttributeValues={":v": int(adds)})
        if len(self._ensured) > 20000:
            self._ensured.clear()

    def _set_max(self, pk, sk, attr, value):
        try:
            self.table.update_item(Key={"pk": pk, "sk": sk}, UpdateExpression="SET #a = :v",
                                   ConditionExpression="attribute_not_exists(#a) OR #a < :v",
                                   ExpressionAttributeNames={"#a": attr}, ExpressionAttributeValues={":v": int(value)})
        except Exception as exc:
            if not self._is_condition_failed(exc):
                raise

    def _set_fields(self, pk, sk, fields):
        if not fields:
            return
        names, values, parts = {}, {}, []
        for i, (k, v) in enumerate(fields.items()):
            names[f"#f{i}"] = k
            values[f":v{i}"] = dynamo_safe(v)
            parts.append(f"#f{i} = :v{i}")
        self.table.update_item(Key={"pk": pk, "sk": sk}, UpdateExpression="SET " + ", ".join(parts),
                               ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    def _query(self, pk, sk_from, sk_to):
        from boto3.dynamodb.conditions import Key

        items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(sk_from, sk_to)}
        while True:
            resp = self.table.query(**kwargs)
            items.extend(resp.get("Items") or [])
            last = resp.get("LastEvaluatedKey")
            if not last:
                return items
            kwargs["ExclusiveStartKey"] = last


# ---------------------------------------------------------------------------
# selección por entorno
# ---------------------------------------------------------------------------

_STORE: Optional[BaseStore] = None
_STORE_LOCK = threading.Lock()


def store_kind() -> str:
    return (os.environ.get("APIS_STORE") or "dynamodb").strip().lower()


def get_store() -> BaseStore:
    """Singleton según APIS_STORE (dynamodb | memory) y APIS_TABLE."""
    global _STORE
    if _STORE is None:
        with _STORE_LOCK:
            if _STORE is None:
                if store_kind() == "memory":
                    _STORE = MemoryStore()
                else:
                    _STORE = DynamoStore(os.environ.get("APIS_TABLE") or TABLE_DEFAULT)
                _log(f"tienda {_STORE.name}" + (f" (tabla {_STORE.table_name})" if _STORE.name == "dynamodb" else ""))
    return _STORE


def reset_store() -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = None
