"""Role-specific home data, matching the original profile-management portal."""
import infrastructure
import measurement_reports
import profiles
from settings_service import score_band


def summary(user):
    role = profiles.profile_of(user)
    if role == "admin":
        return {"profile": role}
    history = measurement_reports.history(
        profiles.store_scope(user), captured_by=profiles.reading_author(user)
    )
    rows = history["rows"]
    if role == "viewer":
        stores = {store["code"]: store for store in infrastructure.list_stores(include_deleted=True)}
        scores = {}
        for row in rows:
            if row["status"] == "Aprobado" and row["score"] is not None:
                scores.setdefault(row["store_id"], []).append(row["score"])
        locations = []
        for code, values in scores.items():
            store = stores.get(code, {})
            average = sum(values) / len(values)
            locations.append({
                "code": code, "name": store.get("name") or code,
                "region": store.get("region", ""), "commune": store.get("commune", ""),
                "manager": store.get("manager", ""), "score": round(average, 1),
                "score_band": score_band(average), "_average": average,
            })
        locations.sort(key=lambda location: (location["_average"], location["name"].casefold(), location["code"]))
        for location in locations:
            location.pop("_average")
        return {"profile": role, "attention": locations[:5],
                "rejected": [row for row in rows if row["status"] == "Rechazado"][:8]}
    own = [row for row in rows if row["captured_by"] == user["username"]]
    rejected = [row for row in own if row["status"] == "Rechazado"]
    pending = [row for row in rows if row["status"] == "En revisión"]
    return {"profile": role, "totals": {"own": len(own), "rejected": len(rejected), "pending": len(pending)},
            "pending": pending[:8] if role == "analyst" else [],
            "rejected": rejected, "recent": own[:8]}
