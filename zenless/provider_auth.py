from __future__ import annotations

import json
from urllib.parse import urlparse


def authentication_script(provider: str, inputs: tuple[str, ...], origin_url: str = "") -> str:
    account_selectors = {
        "chatgpt": [
            '[data-testid="accounts-profile-button"]',
            '[data-testid="user-menu-button"]',
            'button[aria-label*="User menu"]',
            '[aria-label="Open profile menu"]',
            '[aria-label="Abrir menu de perfil"]',
            '[data-testid="profile-button"]',
        ],
        "deepseek": ['[class*="user-avatar"]', '[class*="userAvatar"]', '[data-testid="user-avatar"]', '[class*="ds-avatar"] img', '[aria-label="User menu"]'],
        "gemini": ['a[aria-label*="Google Account"]', 'a[aria-label*="Conta do Google"]', "[data-ogsr-up] img"],
        "hunyuan": ['[class*="user-avatar"]', '[class*="userAvatar"]', '[data-testid="user-avatar"]'],
    }
    expected_host = urlparse(origin_url).hostname or ""
    return f"""(() => {{
      const expectedHost = {json.dumps(expected_host)};
      const sameProvider = !expectedHost || location.hostname === expectedHost;
      const visible = node => {{
        if (!node) return false;
        const style = getComputedStyle(node), box = node.getBoundingClientRect();
        return style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
      }};
      const any = selectors => selectors.some(selector => [...document.querySelectorAll(selector)].some(node => visible(node) || [...node.querySelectorAll('img, span, svg')].some(visible)));
      const composer = any({json.dumps(inputs)});
      const guest = [...document.querySelectorAll('button, a, [role="button"]')].some(node => visible(node) && /^(log in|sign in|sign up|entrar|fazer login|iniciar sessão|登录|登入)$/i.test((node.innerText || node.textContent || '').trim()));
      const account = any({json.dumps(account_selectors.get(provider, []))});
      const authPage = /(?:^|\\/)(?:login|signin|sign-in|auth)(?:\\/|$)/i.test(location.pathname) ||
        /^(?:accounts\\.google\\.com|auth\\.openai\\.com|auth0\\.openai\\.com)$/.test(location.hostname);
      return {{ready: composer && account && !authPage && !guest && sameProvider, composer, authenticated: account && !authPage && !guest && sameProvider}};
    }})()"""


def model_options_script(model: str = "") -> str:
    return f"""(() => {{
      const wanted = {json.dumps(model)}.trim().toLowerCase();
      const visible = node => {{ const b = node.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(node).visibility !== 'hidden'; }};
      const modelLabel = value => /^(?:gpt[- ]|o[1-9](?:[- ]|$)|chatgpt|deepseek|gemini|qwen|hunyuan|hunyuan3d)/i.test(value);
      const candidates = [...document.querySelectorAll('[data-model], [role="option"], [role="menuitem"], button')].filter(node => {{
        const text = (node.innerText || node.textContent || '').trim();
        return visible(node) && (node.hasAttribute('data-model') || modelLabel(text)) && text.length <= 120;
      }});
      if (wanted) {{
        const found = candidates.find(node => (node.getAttribute('data-model') || '').toLowerCase() === wanted || (node.innerText || node.textContent || '').trim().toLowerCase() === wanted);
        if (!found) return {{ok: false}};
        found.click(); return {{ok: true, selected: (found.innerText || found.textContent || '').trim()}};
      }}
      return [...new Set(candidates.map(node => (node.getAttribute('data-model') || node.innerText || node.textContent || '').trim()).filter(Boolean))].slice(0,30);
    }})()"""
