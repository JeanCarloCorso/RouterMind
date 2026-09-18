import hmac
import html
import secrets
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


def _csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def _check_csrf(request: Request, supplied: str) -> bool:
    expected = request.session.get("csrf", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def _with_status(response: HTMLResponse, status_code: int) -> HTMLResponse:
    response.status_code = status_code
    return response


def _page(title: str, content: str) -> HTMLResponse:
    document = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · RouteMind</title>
<style>
:root{{--bg:#0b1020;--panel:#151c31;--text:#edf2ff;--muted:#a9b4cc;--accent:#7dd3fc;--danger:#fda4af;--border:#2b3656}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}}
main{{width:min(760px,calc(100% - 32px));margin:48px auto}} .card{{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:24px;margin:18px 0}}
h1,h2{{line-height:1.2}} h1{{color:var(--accent)}} label{{display:block;margin:14px 0 5px}} input{{width:100%;padding:11px;border-radius:8px;border:1px solid var(--border);background:#0e1528;color:var(--text)}}
button,.button{{display:inline-block;margin-top:16px;padding:10px 15px;border:0;border-radius:8px;background:var(--accent);color:#07111f;font-weight:700;text-decoration:none;cursor:pointer}}
.danger{{background:var(--danger)}} .muted{{color:var(--muted)}} .error{{color:var(--danger)}} code{{overflow-wrap:anywhere;color:#bae6fd}} table{{width:100%;border-collapse:collapse}} td,th{{padding:10px 5px;border-bottom:1px solid var(--border);text-align:left}} nav{{display:flex;justify-content:space-between;align-items:center}} form.inline{{display:inline}}
</style></head><body><main>{content}</main></body></html>"""
    response = HTMLResponse(document)
    response.headers["Cache-Control"] = "no-store"
    return response


def _login_required(request: Request):
    user_id = request.session.get("user_id")
    return request.app.state.database.get_user(int(user_id)) if user_id else None


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return _page("Início", "<div class='card'><h1>RouteMind</h1><p>Gateway inteligente e seguro para sua conta OpenRouter.</p><a class='button' href='/login'>Entrar</a> <a class='button' href='/register'>Criar conta</a></div>")


def _auth_form(request: Request, register: bool, error: str = "") -> HTMLResponse:
    action, heading = ("/register", "Criar conta") if register else ("/login", "Entrar")
    password_help = "<p class='muted'>Use pelo menos 12 caracteres.</p>" if register else ""
    error_html = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    switch = "Já possui conta? <a href='/login'>Entrar</a>" if register else "Ainda não possui conta? <a href='/register'>Criar conta</a>"
    return _page(heading, f"""<div class='card'><h1>{heading}</h1>{error_html}<form method='post' action='{action}'>
<input type='hidden' name='csrf' value='{_csrf(request)}'><label for='email'>E-mail</label><input id='email' name='email' type='email' autocomplete='email' required maxlength='254'>
<label for='password'>Senha</label><input id='password' name='password' type='password' autocomplete='{'new-password' if register else 'current-password'}' required minlength='12' maxlength='256'>{password_help}
<button type='submit'>{heading}</button></form><p class='muted'>{switch}</p></div>""")


@router.get("/register")
async def register_page(request: Request):
    return _auth_form(request, True)


@router.post("/register")
async def register(request: Request):
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return _with_status(_auth_form(request, True, "Sessão inválida. Recarregue a página."), 403)
    try:
        user = request.app.state.auth.register(str(form.get("email", "")), str(form.get("password", "")))
    except sqlite3.IntegrityError:
        return _auth_form(request, True, "Não foi possível criar a conta com esses dados.")
    except ValueError as exc:
        return _auth_form(request, True, str(exc))
    request.session.clear()
    request.session["user_id"] = user.id
    _csrf(request)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/login")
async def login_page(request: Request):
    return _auth_form(request, False)


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return _with_status(_auth_form(request, False, "Sessão inválida. Recarregue a página."), 403)
    user = request.app.state.auth.authenticate_password(str(form.get("email", "")), str(form.get("password", "")))
    if not user:
        return _auth_form(request, False, "E-mail ou senha inválidos.")
    request.session.clear()
    request.session["user_id"] = user.id
    _csrf(request)
    return RedirectResponse("/dashboard", status_code=303)


def _dashboard(request: Request, user, revealed_key: str | None = None, message: str = "") -> HTMLResponse:
    csrf = _csrf(request)
    rows = request.app.state.database.list_api_keys(user.id)
    key_rows = "".join(
        f"<tr><td>{html.escape(row['label'])}</td><td><code>{html.escape(row['key_prefix'])}…</code></td><td>{'Revogada' if row['revoked_at'] else 'Ativa'}</td><td>" +
        (f"<form class='inline' method='post' action='/keys/{row['id']}/revoke'><input type='hidden' name='csrf' value='{csrf}'><button class='danger'>Revogar</button></form>" if not row["revoked_at"] else "") + "</td></tr>"
        for row in rows
    ) or "<tr><td colspan='4' class='muted'>Nenhuma chave criada.</td></tr>"
    revealed = f"<div class='card'><h2>Copie sua nova chave agora</h2><p>Ela não será exibida novamente.</p><code>{html.escape(revealed_key)}</code></div>" if revealed_key else ""
    notice = f"<p>{html.escape(message)}</p>" if message else ""
    or_status = "Configurada" if user.openrouter_key_encrypted else "Não configurada"
    content = f"""<nav><h1>RouteMind</h1><form method='post' action='/logout'><input type='hidden' name='csrf' value='{csrf}'><button>Sair</button></form></nav>{notice}{revealed}
<div class='card'><h2>Chave OpenRouter</h2><p>Status: <strong>{or_status}</strong></p><form method='post' action='/openrouter-key'><input type='hidden' name='csrf' value='{csrf}'>
<label for='or-key'>Nova chave pessoal OpenRouter</label><input id='or-key' name='openrouter_key' type='password' autocomplete='off' required><p class='muted'>Armazenada criptografada e nunca exibida ou enviada ao navegador novamente.</p><button>Salvar chave</button></form></div>
<div class='card'><h2>Nova chave RouteMind</h2><form method='post' action='/keys'><input type='hidden' name='csrf' value='{csrf}'><label for='label'>Nome</label><input id='label' name='label' maxlength='80' placeholder='Produção' required><button>Gerar chave</button></form></div>
<div class='card'><h2>Chaves RouteMind</h2><table><thead><tr><th>Nome</th><th>Prefixo</th><th>Status</th><th></th></tr></thead><tbody>{key_rows}</tbody></table></div>"""
    return _page("Painel", content)


@router.get("/dashboard")
async def dashboard(request: Request):
    user = _login_required(request)
    return _dashboard(request, user) if user else RedirectResponse("/login", status_code=303)


@router.post("/openrouter-key")
async def save_openrouter_key(request: Request):
    user = _login_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return HTMLResponse("CSRF inválido", status_code=403)
    try:
        encrypted = request.app.state.auth.encrypt_openrouter_key(str(form.get("openrouter_key", "")))
    except ValueError as exc:
        return _dashboard(request, user, message=str(exc))
    request.app.state.database.set_openrouter_key(user.id, encrypted)
    request.app.state.catalog.invalidate(user.id)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/keys")
async def create_key(request: Request):
    user = _login_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return HTMLResponse("CSRF inválido", status_code=403)
    key = request.app.state.auth.issue_api_key(user.id, str(form.get("label", "")))
    return _dashboard(request, request.app.state.database.get_user(user.id), revealed_key=key)


@router.post("/keys/{key_id}/revoke")
async def revoke_key(key_id: int, request: Request):
    user = _login_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return HTMLResponse("CSRF inválido", status_code=403)
    request.app.state.database.revoke_api_key(user.id, key_id)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return HTMLResponse("CSRF inválido", status_code=403)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
