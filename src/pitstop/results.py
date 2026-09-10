"""List-compatible search results with counts before pagination."""


class SearchResults(list):
    def __init__(self, items, *, fetched_count: int, limit: int = 0, freshness=None):
        self.matched_count = len(items)
        self.fetched_count = fetched_count
        self.freshness = freshness or {}
        super().__init__(items[:limit] if limit > 0 else items)

    @property
    def coverage(self) -> dict:
        return {
            "fetched_count": self.fetched_count,
            "matched_count": self.matched_count,
            "returned_count": len(self),
            "truncated": len(self) < self.matched_count,
        }


def coverage_of(items) -> dict:
    return getattr(items, "coverage", {"returned_count": len(items)})
