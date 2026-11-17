"""Client profiles for the session API. API-key clients use their own authorization."""
PROFILE_NAMES = {"admin": "Administrador", "analyst": "Analista", "replenisher": "Reponedor", "viewer": "Superusuario"}
LEGACY_PROFILES = {"supervisor": "analyst", "tienda": "replenisher"}
PROFILES = tuple(PROFILE_NAMES)
INTERNAL_PROFILES = ('local-neura',)
PERMISSIONS = {
    "read": frozenset((*PROFILES, *INTERNAL_PROFILES)),
    "train": frozenset(INTERNAL_PROFILES),
    "scan": frozenset(("analyst", "replenisher")),
    "review": frozenset(("analyst",)),
    "manage": frozenset(("admin",)),
    "report": frozenset(("admin", "analyst", "viewer")),
    "dashboard": frozenset(("analyst", "viewer")),
    "resolve": frozenset(("analyst",)),
}


def profile_of(user):
    role = user if isinstance(user, str) else user.get("profile", user.get("role"))
    return LEGACY_PROFILES.get(role, role) if role in (*PROFILES, *LEGACY_PROFILES, *INTERNAL_PROFILES) else None


def can(user, action):
    if profile_of(user) in INTERNAL_PROFILES and not (isinstance(user, dict) and (user.get('internal') or user.get('is_internal'))):
        return False
    if isinstance(user, dict) and user.get('read_only') and action in ('scan', 'review', 'resolve', 'train'):
        return False
    return profile_of(user) in PERMISSIONS.get(action, ())


def store_scope(user):
    profile = profile_of(user)
    stores = user.get("store_ids") or ([user["store_id"]] if user.get("store_id") else [])
    if profile in ("replenisher", "analyst"):
        return tuple(stores)
    return None if profile in PROFILES or (profile in INTERNAL_PROFILES and (user.get('internal') or user.get('is_internal'))) else ()


def reading_author(user):
    return user["username"] if profile_of(user) == "replenisher" else None
