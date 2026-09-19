import hmac
import html
import secrets
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import markdown

from app.services.database import DuplicateUserError

router = APIRouter()
DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
DOC_PAGES = {
    "README.md": "Visão geral",
    "chat-completions.md": "API de Chat Completions",
    "examples.md": "Exemplos",
}


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
:root{{--bg:#070b14;--panel:#101827;--panel-2:#0b1220;--text:#f3f7ff;--muted:#97a6bc;--accent:#55d6be;--accent-2:#2ebca2;--violet:#8b7cf6;--success:#4ade80;--danger:#fb7185;--border:#22304a;--soft:#151f32;--shadow:0 22px 64px rgba(0,0,0,.28)}}
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;background:radial-gradient(circle at 12% -5%,rgba(85,214,190,.1),transparent 25%),radial-gradient(circle at 95% 3%,rgba(139,124,246,.1),transparent 22%),var(--bg);color:var(--text);font:15px/1.6 Inter,ui-sans-serif,system-ui,sans-serif}} a{{color:var(--accent)}} main{{width:min(1160px,calc(100% - 32px));margin:26px auto 64px}}
h1,h2,h3,p{{margin-top:0}} h1,h2,h3{{line-height:1.18;letter-spacing:-.025em}} h1{{font-size:clamp(1.9rem,4vw,2.7rem)}} h2{{font-size:1.18rem}} .muted{{color:var(--muted)}} .eyebrow{{margin:0 0 7px;color:var(--muted);font-size:.72rem;font-weight:760;text-transform:uppercase;letter-spacing:.14em}}
.card{{background:linear-gradient(145deg,rgba(16,24,39,.98),rgba(11,18,32,.98));border:1px solid var(--border);border-radius:18px;padding:24px;box-shadow:var(--shadow)}} label{{display:block;margin:15px 0 7px;font-weight:680}} input,select{{width:100%;padding:12px 13px;border-radius:10px;border:1px solid var(--border);background:#080f1d;color:var(--text);outline:none;transition:.16s ease}} input:hover,select:hover{{border-color:#344762}} input:focus,select:focus{{border-color:var(--accent);box-shadow:0 0 0 3px rgba(85,214,190,.12)}}
button,.button{{display:inline-flex;align-items:center;justify-content:center;gap:7px;margin-top:15px;padding:10px 15px;border:1px solid transparent;border-radius:10px;background:var(--accent);color:#031511;font-weight:780;text-decoration:none;cursor:pointer;transition:.16s ease}} button:hover,.button:hover{{background:var(--accent-2);color:white;transform:translateY(-1px)}} .button.secondary,button.secondary{{background:transparent;color:var(--text);border-color:var(--border)}} .button.compact{{margin:0;padding:8px 12px}} .danger{{background:transparent!important;color:var(--danger)!important;border-color:rgba(251,113,133,.42)!important}}
.brand{{display:flex;align-items:center;gap:10px;color:var(--text);font-size:1.02rem;font-weight:850;text-decoration:none}} .brand-mark{{display:grid;place-items:center;width:33px;height:33px;border-radius:9px;background:linear-gradient(135deg,var(--accent),var(--violet));color:#06131a;font-weight:900}} .site-nav{{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:42px}} .nav-links{{display:flex;align-items:center;gap:7px}} .nav-link{{padding:8px 11px;border-radius:9px;color:var(--muted);font-weight:650;text-decoration:none}} .nav-link:hover{{background:var(--soft);color:var(--text)}}
.home-shell{{max-width:900px;margin:10vh auto 0}} .home-heading{{max-width:720px}} .home-heading h1{{font-size:clamp(2.35rem,6vw,4.15rem);margin-bottom:17px}} .home-heading p{{max-width:620px;font-size:1.08rem;color:#b8c4d6}} .home-actions{{display:flex;gap:10px;flex-wrap:wrap;margin:26px 0 46px}} .home-actions .button{{margin:0}} .overview{{display:grid;grid-template-columns:repeat(3,1fr);gap:13px}} .overview-item{{padding:20px;border:1px solid var(--border);border-radius:15px;background:rgba(12,19,33,.72)}} .overview-item strong{{display:block;margin-bottom:5px}} .overview-item span{{color:var(--muted);font-size:.9rem}}
.auth-page{{max-width:430px;margin:6vh auto}} .auth-brand{{justify-content:center;margin-bottom:28px}} .auth-card{{padding:30px}} .auth-card h1{{font-size:1.65rem;margin-bottom:7px}} .auth-card button{{width:100%;margin-top:22px}} .auth-switch{{margin:22px 0 0;text-align:center;color:var(--muted)}} .form-hint{{font-size:.84rem;color:var(--muted);margin:7px 0 0}} .error-box{{margin:16px 0;padding:11px 13px;border:1px solid rgba(251,113,133,.35);background:rgba(251,113,133,.08);border-radius:10px;color:#fda4af}}
.app-header{{display:flex;align-items:center;justify-content:space-between;gap:18px;padding-bottom:20px;border-bottom:1px solid var(--border);margin-bottom:30px}} .app-actions{{display:flex;align-items:center;gap:8px}} .app-actions form button{{margin:0}} .dashboard-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}} .dashboard-head h1{{margin-bottom:6px}} .stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:11px;margin-bottom:20px}} .stat{{padding:16px 17px;border:1px solid var(--border);border-radius:14px;background:rgba(12,19,33,.7)}} .stat span{{display:block;color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.08em}} .stat strong{{display:block;margin-top:6px;font-size:1.04rem}}
.dashboard-grid{{display:grid;grid-template-columns:minmax(0,1.18fr) minmax(300px,.82fr);gap:18px;margin:18px 0}} .stack{{display:grid;gap:18px}} .full{{grid-column:1/-1}} .card-head{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}} .card-head h2{{margin-bottom:0}} .status-row{{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:14px 0}} .badge{{display:inline-flex;align-items:center;gap:7px;border-radius:999px;padding:5px 9px;font-size:.78rem;font-weight:750}} .badge.ok{{background:rgba(74,222,128,.1);color:var(--success);border:1px solid rgba(74,222,128,.22)}} .badge.fail{{background:rgba(251,113,133,.1);color:var(--danger);border:1px solid rgba(251,113,133,.22)}} .badge.off{{background:rgba(148,163,184,.08);color:var(--muted);border:1px solid var(--border)}} .dot{{width:6px;height:6px;border-radius:50%;background:currentColor}}
.notice{{margin:15px 0;border:1px solid rgba(85,214,190,.22);padding:12px 14px;background:rgba(85,214,190,.07);border-radius:10px}} .secret{{border-color:rgba(74,222,128,.35)}} .secret code{{display:block;padding:13px;background:#07101d;border-radius:9px}} code{{overflow-wrap:anywhere;color:#b9efe5}} .checkbox{{display:flex;gap:9px;align-items:flex-start;color:var(--muted);font-size:.88rem}} .checkbox input{{width:auto;margin-top:4px}} .actions{{display:flex;gap:9px;align-items:center;flex-wrap:wrap}} .actions button{{margin-top:8px}} form.inline{{display:inline}}
.table-wrap{{overflow-x:auto}} table{{width:100%;border-collapse:collapse}} td,th{{padding:13px 9px;border-bottom:1px solid var(--border);text-align:left}} th{{color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.09em}} tbody tr:last-child td{{border-bottom:0}}
.charts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}} .chart{{min-height:290px}} .bars{{height:190px;display:flex;align-items:flex-end;gap:8px;padding-top:18px;border-bottom:1px solid var(--border)}} .bar-col{{height:100%;min-width:0;flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:7px}} .bar{{width:min(32px,80%);min-height:3px;border-radius:6px 6px 2px 2px;background:linear-gradient(180deg,var(--accent),var(--violet))}} .bar.cost{{background:linear-gradient(180deg,#fbbf24,#f97316)}} .bar-label{{max-width:100%;overflow:hidden;text-overflow:ellipsis;color:var(--muted);font-size:.67rem;white-space:nowrap}} .key-bars{{display:grid;gap:13px}} .key-bar-head{{display:flex;justify-content:space-between;gap:12px;font-size:.85rem}} .track{{height:8px;margin-top:5px;border-radius:99px;background:#080f1d;overflow:hidden}} .fill{{height:100%;min-width:3px;border-radius:inherit;background:linear-gradient(90deg,var(--violet),var(--accent))}} .fill.cost{{background:linear-gradient(90deg,#f97316,#fbbf24)}}
.docs-layout{{display:grid;grid-template-columns:230px minmax(0,1fr);gap:22px;align-items:start}} .docs-nav{{position:sticky;top:24px;padding:14px}} .docs-nav a{{display:block;padding:9px 10px;border-radius:8px;color:var(--muted);text-decoration:none}} .docs-nav a:hover,.docs-nav a.active{{background:var(--soft);color:var(--text)}} .docs-article{{min-width:0;padding:34px}} .docs-article h1{{margin-bottom:25px}} .docs-article h2{{margin-top:34px;padding-top:8px;border-top:1px solid var(--border)}} .docs-article h3{{margin-top:26px}} .docs-article p,.docs-article li{{color:#c0cada}} .docs-article pre{{overflow:auto;padding:16px;border:1px solid var(--border);border-radius:11px;background:#070d18}} .docs-article pre code{{color:#d8e2f0}} .docs-article :not(pre)>code{{padding:2px 5px;border-radius:5px;background:#172238}} .docs-article blockquote{{margin-left:0;padding-left:15px;border-left:3px solid var(--accent)}}
@media(max-width:1000px){{.stats{{grid-template-columns:repeat(2,1fr)}}}} @media(max-width:800px){{main{{margin-top:18px}}.overview{{grid-template-columns:1fr}}.dashboard-grid,.docs-layout,.charts{{grid-template-columns:1fr}}.docs-nav{{position:static}}.dashboard-head{{align-items:flex-start;flex-direction:column}}.card{{padding:20px}}td,th{{white-space:nowrap}}.site-nav{{margin-bottom:30px}}.nav-links .nav-link{{display:none}}}} @media(max-width:520px){{.stats{{grid-template-columns:1fr}}}}
</style></head><body><main>{content}</main></body></html>"""
    response = HTMLResponse(document)
    response.headers["Cache-Control"] = "no-store"
    return response


def _login_required(request: Request):
    user_id = request.session.get("user_id")
    return request.app.state.database.get_user(int(user_id)) if user_id else None


def _public_header() -> str:
    return """<header class='site-nav'><a class='brand' href='/'><span class='brand-mark'>R</span>RouteMind</a>
<nav class='nav-links'><a class='nav-link' href='/docs/'>Documentação</a><a class='nav-link' href='/login'>Entrar</a><a class='button compact' href='/register'>Criar conta</a></nav></header>"""


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return _page("Início", _public_header() + """<section class='home-shell'><div class='home-heading'><p class='eyebrow'>Gateway de modelos</p><h1>RouteMind</h1><p>Uma interface central para configurar sua credencial OpenRouter, emitir chaves de acesso e aplicar regras de seleção e custo por requisição.</p></div>
<div class='home-actions'><a class='button' href='/login'>Acessar conta</a><a class='button secondary' href='/docs/'>Consultar documentação</a></div>
<div class='overview'><div class='overview-item'><strong>Credenciais</strong><span>Chaves isoladas por usuário e armazenadas com proteção adequada.</span></div><div class='overview-item'><strong>Roteamento</strong><span>Seleção por capacidade, contexto, preferência e exclusão.</span></div><div class='overview-item'><strong>Custos</strong><span>Modo gratuito por padrão e teto estimado por chamada.</span></div></div></section>""")


def _documentation_page(filename: str) -> HTMLResponse:
    title = DOC_PAGES[filename]
    source = (DOCS_DIR / filename).read_text(encoding="utf-8")
    # Documentation is versioned with the application. Escape raw HTML before
    # rendering so Markdown files cannot inject active markup into the UI.
    article = markdown.markdown(html.escape(source), extensions=["extra", "sane_lists"])
    navigation = "".join(
        f"<a class='{'active' if page == filename else ''}' href='/docs/{page}'>{html.escape(label)}</a>"
        for page, label in DOC_PAGES.items()
    )
    content = f"""<header class='app-header'><a class='brand' href='/'><span class='brand-mark'>R</span>RouteMind</a><div class='app-actions'><a class='nav-link' href='/'>Início</a><a class='button compact' href='/login'>Entrar</a></div></header>
<div class='docs-layout'><aside class='card docs-nav'><p class='eyebrow'>Documentação</p>{navigation}</aside><article class='card docs-article'>{article}</article></div>"""
    return _page(title, content)


@router.get("/docs")
async def documentation_redirect():
    return RedirectResponse("/docs/", status_code=307)


@router.get("/docs/")
async def documentation_index():
    return _documentation_page("README.md")


@router.get("/docs/{filename}")
async def documentation_page(filename: str):
    if filename not in DOC_PAGES:
        return _with_status(
            _page("Documento não encontrado", "<div class='card'><h1>Documento não encontrado</h1><a class='button secondary' href='/docs/'>Voltar</a></div>"),
            404,
        )
    return _documentation_page(filename)


def _auth_form(request: Request, register: bool, error: str = "") -> HTMLResponse:
    action, heading = ("/register", "Criar conta") if register else ("/login", "Entrar")
    name_field = "<label for='name'>Nome</label><input id='name' name='name' type='text' autocomplete='name' required minlength='2' maxlength='120' placeholder='Seu nome'>" if register else ""
    confirmation = "<label for='password-confirmation'>Repita a senha</label><input id='password-confirmation' name='password_confirmation' type='password' autocomplete='new-password' required minlength='12' maxlength='256'>" if register else ""
    password_help = "<p class='form-hint'>Use entre 12 e 256 caracteres.</p>" if register else ""
    error_html = f"<div class='error-box' role='alert'>{html.escape(error)}</div>" if error else ""
    switch = "Já possui conta? <a href='/login'>Entrar</a>" if register else "Ainda não possui conta? <a href='/register'>Criar conta</a>"
    return _page(heading, f"""<div class='auth-page'><a class='brand auth-brand' href='/'><span class='brand-mark'>R</span>RouteMind</a>
<section class='card auth-card'><p class='eyebrow'>{'Cadastro' if register else 'Acesso'}</p><h1>{heading}</h1><p class='muted'>{'Informe seus dados para criar a conta.' if register else 'Entre para acessar suas credenciais e configurações.'}</p>{error_html}<form method='post' action='{action}'>
<input type='hidden' name='csrf' value='{_csrf(request)}'>{name_field}<label for='email'>E-mail</label><input id='email' name='email' type='email' autocomplete='email' required maxlength='254' placeholder='voce@empresa.com'>
<label for='password'>Senha</label><input id='password' name='password' type='password' autocomplete='{'new-password' if register else 'current-password'}' required minlength='12' maxlength='256'>{password_help}
{confirmation}<button type='submit'>{heading}</button></form><p class='auth-switch'>{switch}</p></section></div>""")


@router.get("/register")
async def register_page(request: Request):
    return _auth_form(request, True)


@router.post("/register")
async def register(request: Request):
    form = await request.form()
    if not _check_csrf(request, str(form.get("csrf", ""))):
        return _with_status(_auth_form(request, True, "Sessão inválida. Recarregue a página."), 403)
    password = str(form.get("password", ""))
    if not hmac.compare_digest(password, str(form.get("password_confirmation", ""))):
        return _with_status(_auth_form(request, True, "As senhas não coincidem."), 400)
    try:
        user = request.app.state.auth.register(
            str(form.get("name", "")), str(form.get("email", "")), password
        )
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
    summary = request.app.state.database.request_summary(user.id)
    request_rows = request.app.state.database.list_request_logs(user.id, limit=25)
    charts = request.app.state.database.dashboard_charts(user.id)
    now = datetime.now(UTC).isoformat()
    active_count = sum(not row["revoked_at"] and (not row["expires_at"] or row["expires_at"] > now) for row in rows)
    def key_status(row):
        if row["revoked_at"]:
            return "Revogada", "off"
        if row["expires_at"] and row["expires_at"] <= now:
            return "Expirada", "fail"
        return "Ativa", "ok"

    def date_label(value):
        return "Nunca" if not value else f"{str(value)[:19].replace('T', ' ')} UTC"

    def key_action(row):
        if row["revoked_at"] or key_status(row)[0] == "Expirada":
            return "—"
        return f"<a class='button danger compact' href='/keys/{row['id']}/delete'>Revogar</a>"

    key_rows = "".join(
        f"<tr><td><strong>{html.escape(row['label'])}</strong></td><td><code>{html.escape(row['key_prefix'])}…</code></td>"
        f"<td><span class='badge {key_status(row)[1]}'><span class='dot'></span>{key_status(row)[0]}</span></td>"
        f"<td>{date_label(row['expires_at'])}</td><td>{date_label(row['last_used_at'])}</td>"
        f"<td>{key_action(row)}</td></tr>"
        for row in rows
    ) or "<tr><td colspan='6' class='muted'>Nenhuma chave criada.</td></tr>"
    def format_cost(value) -> str:
        return "—" if value is None else f"US$ {value:.6f}"

    request_history = "".join(
        f"<tr><td>{html.escape(str(row['created_at'])[:19].replace('T', ' '))} UTC</td>"
        f"<td><span class='badge {'ok' if row['success'] else 'fail'}'><span class='dot'></span>{'Sucesso' if row['success'] else 'Erro'}</span></td>"
        f"<td>{html.escape(row.get('api_key_label') or 'Legado')}<br><code>{html.escape(row.get('api_key_prefix') or '—')}</code></td>"
        f"<td><code>{html.escape(row['model'] or '—')}</code></td><td>{row['status_code']}</td>"
        f"<td>{row['prompt_tokens'] if row['prompt_tokens'] is not None else '—'}</td>"
        f"<td>{row['completion_tokens'] if row['completion_tokens'] is not None else '—'}</td>"
        f"<td>{row['total_tokens'] if row['total_tokens'] is not None else '—'}</td>"
        f"<td>{format_cost(row['cost_usd'])}</td>"
        f"<td>{row['response_time_ms']} ms</td></tr>"
        for row in request_rows
    ) or "<tr><td colspan='10' class='muted'>Nenhuma requisição registrada ainda.</td></tr>"

    def daily_bars(field: str, formatter, css_class: str = "") -> str:
        maximum = max(1.0, max((float(row[field] or 0) for row in charts["by_day"]), default=0))
        return "".join(
            f"<div class='bar-col' title='{html.escape(formatter(row[field] or 0))}'>"
            f"<div class='bar {css_class}' style='height:{max(3, round(float(row[field] or 0) / maximum * 100))}%'></div>"
            f"<span class='bar-label'>{html.escape(str(row['label'])[5:])}</span></div>"
            for row in charts["by_day"]
        ) or "<p class='muted'>Os dados aparecerão após a primeira requisição.</p>"

    def key_bars(field: str, formatter, css_class: str = "") -> str:
        maximum = max(1.0, max((float(row[field] or 0) for row in charts["by_key"]), default=0))
        return "".join(
            f"<div><div class='key-bar-head'><span>{html.escape(row['label'])}</span><strong>{html.escape(formatter(row[field] or 0))}</strong></div>"
            f"<div class='track'><div class='fill {css_class}' style='width:{max(1, round(float(row[field] or 0) / maximum * 100))}%'></div></div></div>"
            for row in charts["by_key"]
        ) or "<p class='muted'>Nenhuma chave criada.</p>"

    token_label = lambda value: f"{int(value):,} tokens"
    cost_label = lambda value: f"US$ {float(value):.6f}"
    token_day_bars = daily_bars("tokens", token_label)
    cost_day_bars = daily_bars("cost_usd", cost_label, "cost")
    token_key_bars = key_bars("tokens", token_label)
    cost_key_bars = key_bars("cost_usd", cost_label, "cost")
    revealed = f"<div class='card secret'><p class='eyebrow'>Nova credencial</p><h2>Copie sua chave RouteMind agora</h2><p class='muted'>Por segurança, ela não será exibida novamente.</p><code>{html.escape(revealed_key)}</code></div>" if revealed_key else ""
    notice = f"<div class='notice'>{html.escape(message)}</div>" if message else ""
    if user.openrouter_key_encrypted:
        openrouter_card = f"""<div class='card'><div class='card-head'><div><p class='eyebrow'>Credencial do provedor</p><h2>Chave OpenRouter</h2></div><span class='badge ok'><span class='dot'></span>Configurada</span></div>
<p class='muted'>Pronta para encaminhar requisições.</p>
<p class='muted'>A chave está criptografada e não pode ser visualizada. Para cadastrar outra, exclua primeiro a credencial atual.</p>
<form method='post' action='/openrouter-key/delete'><input type='hidden' name='csrf' value='{csrf}'>
<label class='checkbox'><input type='checkbox' name='confirm' value='yes' required><span>Confirmo que as chamadas da API deixarão de funcionar até uma nova chave ser cadastrada.</span></label>
<button type='submit' class='danger'>Excluir chave OpenRouter</button></form></div>"""
    else:
        openrouter_card = f"""<div class='card'><div class='card-head'><div><p class='eyebrow'>Credencial do provedor</p><h2>Chave OpenRouter</h2></div><span class='badge off'><span class='dot'></span>Não configurada</span></div>
<p class='muted'>Cadastre uma única chave pessoal. Ela será criptografada e não voltará a ser exibida.</p>
<form method='post' action='/openrouter-key'><input type='hidden' name='csrf' value='{csrf}'>
<label for='or-key'>Chave pessoal OpenRouter</label><input id='or-key' name='openrouter_key' type='password' autocomplete='off' placeholder='sk-or-v1-…' required>
<button type='submit'>Salvar chave</button></form></div>"""
    total_requests = int(summary["total"] or 0)
    successful_requests = int(summary["successful"] or 0)
    failed_requests = int(summary["failed"] or 0)
    total_tokens = int(summary["total_tokens"] or 0)
    total_cost_usd = summary["total_cost_usd"] or 0
    average_ms = round(float(summary["average_response_time_ms"] or 0))
    content = f"""<header class='app-header'><a class='brand' href='/dashboard'><span class='brand-mark'>R</span>RouteMind</a><div class='app-actions'><a class='nav-link' href='/docs/'>Documentação</a><form method='post' action='/logout'><input type='hidden' name='csrf' value='{csrf}'><button type='submit' class='secondary compact'>Sair</button></form></div></header>
<section class='dashboard-head'><div><p class='eyebrow'>Dashboard</p><h1>Olá, {html.escape(user.name)}</h1><p class='muted'>{html.escape(user.email)}</p></div></section>
<section class='stats'><div class='stat'><span>Requisições</span><strong>{total_requests}</strong></div><div class='stat'><span>Bem-sucedidas</span><strong>{successful_requests}</strong></div><div class='stat'><span>Com erro</span><strong>{failed_requests}</strong></div><div class='stat'><span>Tokens</span><strong>{total_tokens:,}</strong></div><div class='stat'><span>Gasto conhecido</span><strong>US$ {total_cost_usd:.6f}</strong></div><div class='stat'><span>Tempo médio</span><strong>{average_ms} ms</strong></div></section>{notice}{revealed}
<div class='dashboard-grid'><div class='stack'>{openrouter_card}</div>
<div class='card'><div class='card-head'><div><p class='eyebrow'>Acesso à API</p><h2>Gerar chave RouteMind</h2></div></div><p class='muted'>Crie um Bearer token para uma aplicação ou ambiente.</p><form method='post' action='/keys'><input type='hidden' name='csrf' value='{csrf}'><label for='label'>Identificação</label><input id='label' name='label' maxlength='80' placeholder='Ex.: Produção' required><label for='expiration'>Expiração</label><select id='expiration' name='expiration'><option value='1h'>1 hora</option><option value='1d'>1 dia</option><option value='7d'>7 dias</option><option value='30d'>30 dias</option><option value='90d'>90 dias</option><option value='180d'>180 dias</option><option value='1y'>1 ano</option><option value='never' selected>Nunca expira</option></select><button type='submit'>Gerar chave</button></form></div>
<section class='charts full'><div class='card chart'><div class='card-head'><div><p class='eyebrow'>Tokens</p><h2>Uso de tokens por dia</h2></div><span class='muted'>14 dias com atividade</span></div><div class='bars'>{token_day_bars}</div></div><div class='card chart'><div class='card-head'><div><p class='eyebrow'>Tokens</p><h2>Uso de tokens por chave</h2></div></div><div class='key-bars'>{token_key_bars}</div></div><div class='card chart'><div class='card-head'><div><p class='eyebrow'>Custo efetivo</p><h2>Gasto em USD por dia</h2></div><span class='muted'>14 dias com atividade</span></div><div class='bars'>{cost_day_bars}</div></div><div class='card chart'><div class='card-head'><div><p class='eyebrow'>Custo efetivo</p><h2>Gasto em USD por chave</h2></div></div><div class='key-bars'>{cost_key_bars}</div></div></section>
<div class='card full'><div class='card-head'><div><p class='eyebrow'>Credenciais de acesso</p><h2>Chaves RouteMind</h2></div><span class='muted'>{active_count} ativas · {len(rows)} no histórico</span></div><div class='table-wrap'><table><thead><tr><th>Nome</th><th>Prefixo</th><th>Status</th><th>Expira</th><th>Último uso</th><th>Ação</th></tr></thead><tbody>{key_rows}</tbody></table></div></div>
<div class='card full'><div class='card-head'><div><p class='eyebrow'>Uso recente</p><h2>Histórico de requisições</h2></div><span class='muted'>Últimas 25</span></div><div class='table-wrap'><table><thead><tr><th>Data</th><th>Resultado</th><th>Chave</th><th>Modelo</th><th>HTTP</th><th>Entrada</th><th>Saída</th><th>Total</th><th>Custo</th><th>Tempo</th></tr></thead><tbody>{request_history}</tbody></table></div></div></div>"""
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
    try:
        key = request.app.state.auth.issue_api_key(
            user.id, str(form.get("label", "")), str(form.get("expiration", "never"))
        )
    except ValueError as exc:
        return _with_status(_dashboard(request, user, message=str(exc)), 400)
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
<div class='notice'>A chave será revogada, mas permanecerá no histórico para preservar as métricas das requisições associadas.</div>
<div class='actions'><a class='button secondary' href='/dashboard'>Cancelar</a><form class='inline' method='post' action='/keys/{key_id}/delete'><input type='hidden' name='csrf' value='{csrf}'><button type='submit' class='danger'>Confirmar revogação</button></form></div></div>"""
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
