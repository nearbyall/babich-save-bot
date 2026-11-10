from .i18n import t


class UserError(Exception):
    """An error for the user: a key of i18n.TEXTS, put into words when shown, in the language of whoever sees it.
    Several users may wait on one download and get its error."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key, self.params = key, params

    def __str__(self) -> str:
        return t(self.key, **self.params)
