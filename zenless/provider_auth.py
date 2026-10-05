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
      const visible = node => {{
        if (!node) return false;
        const style = getComputedStyle(node), box = node.getBoundingClientRect();
        return style.visibility !== 'hidden' && style.display !== 'none' && box.width > 0 && box.height > 0;
      }};
      const textOf = node => (node?.innerText || node?.textContent || '').trim();
      const modelLabel = value => /(?:^|\\b)(?:gpt[- ]?|o[1-9](?:[- ]|\\b)|chatgpt|deepseek|gemini|qwen|hunyuan|hunyuan3d)/i.test(value);
      const optionNodes = () => [...document.querySelectorAll('[data-model], [role="option"], [role="menuitem"], [role="menuitemradio"]')].filter(node => {{
        const text = textOf(node);
        return visible(node) && text.length <= 160 && (node.hasAttribute('data-model') || modelLabel(text));
      }});
      const buttonOptions = () => [...document.querySelectorAll('button')].filter(node => {{
        const text = textOf(node);
        const testid = (node.getAttribute('data-testid') || '').toLowerCase();
        return visible(node) && text.length <= 160 && modelLabel(text) && /model|switch|picker|selector|option/.test(testid);
      }});
      const candidates = () => [...optionNodes(), ...buttonOptions()];
      const exact = node => {{
        const id = (node.getAttribute('data-model') || '').trim().toLowerCase();
        const text = textOf(node).toLowerCase();
        return id === wanted || text === wanted;
      }};
      if (wanted) {{
        const found = candidates().find(exact);
        if (found) {{
          found.click();
          return {{ok: true, selected: textOf(found) || found.getAttribute('data-model') || {json.dumps(model)}}};
        }}
      }} else {{
        const values = [...new Set(candidates().map(node => (node.getAttribute('data-model') || textOf(node)).trim()).filter(Boolean))];
        if (values.length > 1 || values.some(value => modelLabel(value))) return values.slice(0, 30);
      }}

      const triggers = [...document.querySelectorAll('button, [role="button"], [role="combobox"]')].filter(node => {{
        if (!visible(node) || node.matches('[role="option"], [role="menuitem"], [role="menuitemradio"]')) return false;
        const text = textOf(node);
        const meta = [
          node.getAttribute('aria-label') || '',
          node.getAttribute('data-testid') || '',
          node.getAttribute('title') || '',
          node.getAttribute('id') || '',
        ].join(' ').toLowerCase();
        return /model|modelo|模型|switcher|selector|picker/.test(meta) || (text.length <= 80 && modelLabel(text));
      }});
      if (triggers.length) {{
        triggers[0].click();
        return wanted ? {{ok: false, opened: true}} : [];
      }}
      return wanted ? {{ok: false, opened: false}} : [];
    }})()"""
