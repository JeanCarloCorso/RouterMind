async def test_public_pages_and_markdown_documentation(make_client):
    client, _ = make_client([])

    home = await client.get("/")
    assert home.status_code == 200
    assert "Uma interface central" in home.text
    assert "Consultar documentação" in home.text

    login = await client.get("/login")
    assert login.status_code == 200
    assert "Entre para acessar suas credenciais" in login.text

    register = await client.get("/register")
    assert register.status_code == 200
    assert "Informe seus dados para criar a conta" in register.text
    assert "name='password_confirmation'" in register.text

    docs_redirect = await client.get("/docs", follow_redirects=False)
    assert docs_redirect.status_code == 307
    assert docs_redirect.headers["location"] == "/docs/"

    docs = await client.get("/docs/")
    assert docs.status_code == 200
    assert "Documentação do RouteMind" in docs.text
    assert "docs-layout" in docs.text

    api_docs = await client.get("/docs/chat-completions.md")
    assert api_docs.status_code == 200
    assert "API de Chat Completions do RouteMind" in api_docs.text
    assert "<table>" in api_docs.text
    assert "&amp;quot;" not in api_docs.text

    examples = await client.get("/docs/examples.md")
    assert examples.status_code == 200
    assert "&quot;messages&quot;" in examples.text
    assert "&amp;quot;" not in examples.text

    missing = await client.get("/docs/unknown.md")
    assert missing.status_code == 404
