from collections.abc import AsyncIterator
from typing import Protocol

import httpx
from githubkit import GitHub
from githubkit_schemas.latest.models import Release

from craft_dl.models import AssetInfo, ReleaseInfo

ORG = "storytold"


class ReleaseSource(Protocol):
    def list_releases(self, repo: str) -> AsyncIterator[ReleaseInfo]: ...

    async def latest_release(self, repo: str) -> ReleaseInfo: ...
# end class


def to_release_info(release: Release) -> ReleaseInfo:
    return ReleaseInfo(
        tag=release.tag_name,
        name=release.name or release.tag_name,
        body=release.body or "",
        assets=[AssetInfo(name=a.name, size=a.size, url=a.url) for a in release.assets],
    )
# end def


class GitHubClient:
    def __init__(self, token: str | None) -> None:
        self.token = token
        self.api = GitHub(token) if token else GitHub()
    # end def

    async def list_org_repos(self, org: str = ORG) -> list[str]:
        return [repo.name async for repo in self.api.paginate(self.api.rest.repos.async_list_for_org, org=org, type="all")]
    # end def

    async def list_releases(self, repo: str) -> AsyncIterator[ReleaseInfo]:
        async for release in self.api.paginate(self.api.rest.repos.async_list_releases, owner=ORG, repo=repo):
            yield to_release_info(release)
        # end for
    # end def

    async def latest_release(self, repo: str) -> ReleaseInfo:
        response = await self.api.rest.repos.async_get_latest_release(owner=ORG, repo=repo)
        return to_release_info(response.parsed_data)
    # end def

    def download_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/octet-stream"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        # end if
        return headers
    # end def

    def http_client(self) -> httpx.AsyncClient:
        """For asset bytes. httpx drops the auth header on the cross-host redirect to the object storage."""
        return httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0), headers=self.download_headers())
    # end def
# end class
