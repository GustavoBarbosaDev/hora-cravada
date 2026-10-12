import uuid
from dataclasses import dataclass

from httpx import AsyncClient

PASSWORD = "senha-forte-123"


@dataclass
class Company:
    slug: str
    owner_email: str
    owner_id: str
    tenant_id: str


async def signup(client: AsyncClient, name: str = "Barbearia do Seu Zé") -> Company:
    slug = f"t-{uuid.uuid4().hex[:12]}"
    email = f"dono@{slug}.com.br"
    response = await client.post(
        "/tenants",
        json={
            "tenant_name": name,
            "slug": slug,
            "owner_email": email,
            "owner_password": PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Company(slug, email, body["owner_id"], body["tenant"]["id"])


async def login(client: AsyncClient, company: Company, email: str | None = None) -> dict[str, str]:
    response = await client.post(
        "/auth/login",
        json={
            "tenant_slug": company.slug,
            "email": email or company.owner_email,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    tokens: dict[str, str] = response.json()
    return tokens


def bearer(tokens: dict[str, str]) -> dict[str, str]:
    return {"authorization": f"Bearer {tokens['access_token']}"}


async def owner_headers(client: AsyncClient) -> tuple[Company, dict[str, str]]:
    company = await signup(client)
    return company, bearer(await login(client, company))


async def add_user(
    client: AsyncClient,
    owner: dict[str, str],
    role: str,
    resource_id: str | None = None,
) -> str:
    """Cria um usuário e devolve o e-mail; a senha é sempre `PASSWORD`."""
    email = f"{role}-{uuid.uuid4().hex[:8]}@exemplo.com.br"
    response = await client.post(
        "/users",
        headers=owner,
        json={"email": email, "password": PASSWORD, "role": role, "resource_id": resource_id},
    )
    assert response.status_code == 201, response.text
    return email
