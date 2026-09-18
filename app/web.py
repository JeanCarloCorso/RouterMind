import hmac
import html
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.database import DuplicateUserError

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
:root{{--bg:#080d19;--panel:#121a2b;--panel-2:#0e1627;--text:#eef4ff;--muted:#94a3b8;--accent:#38bdf8;--accent-2:#0ea5e9;--success:#4ade80;--danger:#fb7185;--border:#26334d;--shadow:0 18px 50px rgba(0,0,0,.24)}}
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;background:radial-gradient(circle at 10% 0,#10213c 0,transparent 34%),var(--bg);color:var(--text);font:16px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}}
main{{width:min(1080px,calc(100% - 32px));margin:36px auto 64px}} .card{{background:linear-gradient(145deg,var(--panel),var(--panel-2));border:1px solid var(--border);border-radius:18px;padding:24px;box-shadow:var(--shadow)}}
h1,h2,h3,p{{margin-top:0}} h1,h2{{line-height:1.2}} h1{{color:var(--accent);letter-spacing:-.03em}} h2{{font-size:1.18rem}} label{{display:block;margin:14px 0 6px;font-weight:650}} input{{width:100%;padding:12px 13px;border-radius:10px;border:1px solid var(--border);background:#091222;color:var(--text);outline:none}} input:focus{{border-color:var(--accent);box-shadow:0 0 0 3px rgba(56,189,248,.13)}}
button,.button{{display:inline-flex;align-items:center;justify-content:center;margin-top:16px;padding:10px 16px;border:1px solid transparent;border-radius:10px;background:var(--accent);color:#04111d;font-weight:750;text-decoration:none;cursor:pointer}} button:hover,.button:hover{{background:var(--accent-2);color:white}} .button.secondary,button.secondary{{background:transparent;color:var(--text);border-color:var(--border)}}
.danger{{background:transparent!important;color:var(--danger)!important;border-color:rgba(251,113,133,.45)!important}} .muted{{color:var(--muted)}} .error{{color:var(--danger)}} code{{overflow-wrap:anywhere;color:#bae6fd}} table{{width:100%;border-collapse:collapse}} td,th{{padding:13px 8px;border-bottom:1px solid var(--border);text-align:left}} th{{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.08em}} nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}} nav h1{{margin:0}} form.inline{{display:inline}}
.dashboard-grid{{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(280px,.85fr);gap:20px;margin:20px 0}} .stack{{display:grid;gap:20px}} .eyebrow{{margin:0 0 5px;color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.12em}} .welcome{{font-size:1.45rem;margin-bottom:4px}} .status-row{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:18px 0}} .badge{{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:6px 11px;font-size:.84rem;font-weight:750}} .badge.ok{{background:rgba(74,222,128,.12);color:var(--success);border:1px solid rgba(74,222,128,.25)}} .badge.off{{background:rgba(148,163,184,.1);color:var(--muted);border:1px solid var(--border)}} .dot{{width:7px;height:7px;border-radius:50%;background:currentColor}} .notice{{border-left:3px solid var(--accent);padding:12px 16px;background:rgba(56,189,248,.08);border-radius:8px}} .secret{{border-color:rgba(74,222,128,.4)}} .secret code{{display:block;padding:13px;background:#07101d;border-radius:9px}} .actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}} .actions button{{margin-top:8px}} .checkbox{{display:flex;gap:9px;align-items:flex-start;color:var(--muted);font-size:.9rem}} .checkbox input{{width:auto;margin-top:4px}} .table-wrap{{overflow-x:auto}} .full{{grid-column:1/-1}}
@media(max-width:760px){{main{{margin-top:22px}}.dashboard-grid{{grid-template-columns:1fr}}nav{{align-items:flex-start}}.card{{padding:19px}}td,th{{white-space:nowrap}}}}
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
    except DuplicateUserError:
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
    active_count = len(rows)
    key_rows = "".join(
        f"<tr><td><strong>{html.escape(row['label'])}</strong></td><td><code>{html.escape(row['key_prefix'])}…</code></td><td><span class='badge ok'><span class='dot'></span>Ativa</span></td><td><a class='button danger' href='/keys/{row['id']}/delete'>Excluir</a></td></tr>"
        for row in rows
    ) or "<tr><td colspan='4' class='muted'>Nenhuma chave criada.</td></tr>"
    revealed = f"<div class='card secret'><p class='eyebrow'>Nova credencial</p><h2>Copie sua chave RouteMind agora</h2><p class='muted'>Por segurança, ela não será exibida novamente.</p><code>{html.escape(revealed_key)}</code></div>" if revealed_key else ""
    notice = f"<div class='notice'>{html.escape(message)}</div>" if message else ""
    if user.openrouter_key_encrypted:
        openrouter_card = f"""<div class='card'><p class='eyebrow'>Credencial do provedor</p><h2>Chave OpenRouter</h2>
<div class='status-row'><span class='badge ok'><span class='dot'></span>Configurada</span><span class='muted'>Pronta para encaminhar requisições.</span></div>
<p class='muted'>A chave está criptografada e não pode ser visualizada. Para cadastrar outra, exclua primeiro a credencial atual.</p>
<form method='post' action='/openrouter-key/delete'><input type='hidden' name='csrf' value='{csrf}'>
<label class='checkbox'><input type='checkbox' name='confirm' value='yes' required><span>Confirmo que as chamadas da API deixarão de funcionar até uma nova chave ser cadastrada.</span></label>
<button type='submit' class='danger'>Excluir chave OpenRouter</button></form></div>"""
    else:
        openrouter_card = f"""<div class='card'><p class='eyebrow'>Credencial do provedor</p><h2>Chave OpenRouter</h2>
<div class='status-row'><span class='badge off'><span class='dot'></span>Não configurada</span></div>
<p class='muted'>Cadastre uma única chave pessoal. Ela será criptografada e não voltará a ser exibida.</p>
<form method='post' action='/openrouter-key'><input type='hidden' name='csrf' value='{csrf}'>
<label for='or-key'>Chave pessoal OpenRouter</label><input id='or-key' name='openrouter_key' type='password' autocomplete='off' placeholder='sk-or-v1-…' required>
<button type='submit'>Salvar chave</button></form></div>"""
    content = f"""<nav><div><p class='eyebrow'>Painel</p><h1>RouteMind</h1></div><form method='post' action='/logout'><input type='hidden' name='csrf' value='{csrf}'><button type='submit' class='secondary'>Sair</button></form></nav>
<section><p class='eyebrow'>Conta</p><h2 class='welcome'>Olá, {html.escape(user.email)}</h2><p class='muted'>{active_count} chave{'s' if active_count != 1 else ''} RouteMind ativa{'s' if active_count != 1 else ''}</p></section>{notice}{revealed}
<div class='dashboard-grid'><div class='stack'>{openrouter_card}</div>
<div class='card'><p class='eyebrow'>Acesso à API</p><h2>Gerar chave RouteMind</h2><p class='muted'>Use esta chave como Bearer token nas suas aplicações.</p><form method='post' action='/keys'><input type='hidden' name='csrf' value='{csrf}'><label for='label'>Identificação</label><input id='label' name='label' maxlength='80' placeholder='Produção' required><button type='submit'>Gerar nova chave</button></form></div>
<div class='card full'><p class='eyebrow'>Credenciais de acesso</p><h2>Chaves RouteMind</h2><div class='table-wrap'><table><thead><tr><th>Nome</th><th>Prefixo</th><th>Status</th><th>Ação</th></tr></thead><tbody>{key_rows}</tbody></table></div></div></div>"""
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
    if user.openrouter_key_encrypted:
        return _with_status(
            _dashboard(request, user, message="Já existe uma chave OpenRouter configurada. Exclua-a antes de cadastrar outra."),
            409,
        )
    try:
        encrypted = request.app.state.auth.encrypt_openrouter_key(str(form.get("openrouter_key", "")))
    except ValueError as exc:
        return _dashboard(request, user, message=str(exc))
    request.app.state.database.set_openrouter_key(user.id, encrypted)
    request.app.state.catalog.invalidate(user.id)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/openrouter-key/delete")
async def delete_openrouter_key(request: Request):
    user = _login_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return HTMLResponse("CSRF inválido", status_code=403)
    if form.get("confirm") != "yes":
        return _with_status(_dashboard(request, user, message="Confirme a exclusão da chave OpenRouter."), 400)
    request.app.state.database.delete_openrouter_key(user.id)
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


@router.get("/keys/{key_id}/delete")
async def confirm_delete_key(key_id: int, request: Request):
    user = _login_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    key = request.app.state.database.get_api_key(user.id, key_id)
    if not key:
        return _with_status(_page("Chave não encontrada", "<div class='card'><h1>Chave não encontrada</h1><a class='button secondary' href='/dashboard'>Voltar</a></div>"), 404)
    csrf = _csrf(request)
    content = f"""<div class='card'><p class='eyebrow'>Confirmação necessária</p><h1>Excluir chave RouteMind?</h1>
<p>A chave <strong>{html.escape(key['label'])}</strong> (<code>{html.escape(key['key_prefix'])}…</code>) deixará de funcionar imediatamente.</p>
<div class='notice'><strong>Esta ação é permanente.</strong> O hash e todos os metadados desta chave serão removidos do banco e não poderão ser recuperados.</div>
<div class='actions'><a class='button secondary' href='/dashboard'>Cancelar</a><form class='inline' method='post' action='/keys/{key_id}/delete'><input type='hidden' name='csrf' value='{csrf}'><button type='submit' class='danger'>Confirmar exclusão permanente</button></form></div></div>"""
    return _page("Excluir chave", content)


@router.post("/keys/{key_id}/delete")
async def delete_key(key_id: int, request: Request):
    user = _login_required(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return HTMLResponse("CSRF inválido", status_code=403)
    if not request.app.state.database.delete_api_key(user.id, key_id):
        return _with_status(_page("Chave não encontrada", "<div class='card'><h1>Chave não encontrada</h1><a class='button secondary' href='/dashboard'>Voltar</a></div>"), 404)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return HTMLResponse("CSRF inválido", status_code=403)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
