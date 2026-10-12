import asyncio

from httpx import AsyncClient

from tests.helpers import owner_headers
from tests.integration.test_branches_and_resources import create_resource

REQUESTS = 8


async def test_simultaneous_overlapping_rules_let_exactly_one_through(client: AsyncClient) -> None:
    _, headers = await owner_headers(client)
    resource = await create_resource(client, headers)
    url = f"/resources/{resource['id']}/availability-rules"

    responses = await asyncio.gather(
        *(
            client.post(
                url,
                headers=headers,
                json={"weekday": 2, "start": "09:00", "end": f"{10 + i:02d}:00"},
            )
            for i in range(REQUESTS)
        )
    )

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201] + [409] * (REQUESTS - 1)
    stored = (await client.get(url, headers=headers)).json()
    assert len(stored) == 1
