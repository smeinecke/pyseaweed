# vi:si:et:sw=4:sts=4:ts=4


"""PySeaweed exceptions."""


class BadFidFormat(Exception):
    """Raised when the provided fid is not in the expected format."""

    def __init__(self, value: str) -> None:
        """Create a BadFidFormat exception.

        Args:
            value: Message describing the problem.

        """
        super().__init__(value)
        self.value = value

    def __str__(self) -> str:
        """Return string representation of the exception."""
        return repr(self.value)
