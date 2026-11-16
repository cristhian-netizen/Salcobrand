"""Client profiles for the session API. API-key clients use their own authorization."""
PROFILE_NAMES = {"admin": "Administrador", "analyst": "Analista", "replenisher": "Reponedor", "viewer": "Superusuario"}
LEGACY_PROFILES = {"supervisor": "analyst", "tienda": "replenisher"}
PROFILES = tuple(PROFILE_NAMES)
PERMISSIONS = {
    "read": frozenset(PROFILES),
    "scan": frozenset(("analyst", "replenisher")),
    "review": frozenset(("analyst",)),
    "manage": frozenset(("admin",)),
    "report": frozenset(("admin", "analyst", "viewer")),
    "dashboard": frozenset(("admin", "analyst", "viewer")),
    "resolve": frozenset(("analyst",)),
}


def profile_of(user):
    role = user if isinstance(user, str) else user.get("profile", user.get("role"))
    return LEGACY_PROFILES.get(role, role) if role in (*PROFILES, *LEGACY_PROFILES) else None


def can(user, action):
    if isinstance(user, dict) and user.get('read_only') and action in ('scan', 'review', 'resolve'):
        return False
    return profile_of(user) in PERMISSIONS.get(action, ())


def store_scope(user):
    profile = profile_of(user)
    stores = user.get("store_ids") or ([user["store_id"]] if user.get("store_id") else [])
    if profile == "replenisher" or (profile == "analyst" and stores):
        return tuple(stores)
    return None if profile in PROFILES else ()


def reading_author(user):
    return user["username"] if profile_of(user) == "replenisher" else None
