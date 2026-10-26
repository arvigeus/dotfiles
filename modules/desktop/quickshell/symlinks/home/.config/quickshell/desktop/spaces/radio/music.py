"""Radio station operations over the shared account-scoped Music transport."""
from integrations.subsonic import MusicError, NoRedirect, SubsonicClient


class MusicClient(SubsonicClient):
    METHODS = {"getInternetRadioStations", "createInternetRadioStation",
               "updateInternetRadioStation", "deleteInternetRadioStation"}

    def stations(self):
        result = self.request("getInternetRadioStations")
        if "internetRadioStations" not in result:
            raise MusicError("Nextcloud Music omitted its station list; favorites were preserved.")
        value = result["internetRadioStations"]
        rows = value.get("internetRadioStation", []) if isinstance(value, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise MusicError("Nextcloud Music returned an invalid station list.")
        if len(rows) > 1000:
            raise MusicError("Nextcloud Music has more than 1,000 stations; favorites were preserved.")
        for row in rows:
            if not str(row.get("id", "")).isdigit() or not isinstance(row.get("streamUrl"), str):
                raise MusicError("Nextcloud Music returned an invalid station record.")
        return rows
