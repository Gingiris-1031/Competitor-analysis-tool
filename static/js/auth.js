/**
 * auth.js — Analook Supabase Auth 模块
 * 暴露 window._analookAuth 供 app.js 使用
 */

(async function () {
  // ── 从后端 meta 标签读取 Supabase 配置（由 index.html 注入）──────────────
  const SUPABASE_URL  = document.querySelector('meta[name="supabase-url"]')?.content  || '';
  const SUPABASE_ANON = document.querySelector('meta[name="supabase-anon"]')?.content || '';

  if (!SUPABASE_URL || !SUPABASE_ANON) {
    console.warn('[auth] Supabase 配置缺失，Auth 模块未启动');
    window._analookAuth = { user: null, getToken: () => null, showModal: () => {} };
    return;
  }

  // ── 加载 Supabase JS SDK（CDN）──────────────────────────────────────────
  await _loadScript('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js');
  const { createClient } = window.supabase;
  const sb = createClient(SUPABASE_URL, SUPABASE_ANON);

  // ── 状态 ─────────────────────────────────────────────────────────────────
  let _session = null;

  // ── 初始化：恢复本地 session ──────────────────────────────────────────────
  const { data: { session } } = await sb.auth.getSession();
  _session = session;
  // 等 DOM ready 后再更新 UI（按钮/头像元素可能还没渲染）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => _updateUI(session?.user ?? null));
  } else {
    _updateUI(session?.user ?? null);
  }

  // 监听 Auth 状态变化（登录 / 登出 / token 刷新）
  sb.auth.onAuthStateChange((_event, newSession) => {
    _session = newSession;
    _updateUI(newSession?.user ?? null);
    // 登录/登出切换后，重新从服务端拉历史
    if (typeof window.syncServerHistory === 'function') {
      window.syncServerHistory();
    }
  });

  // ── 公开接口 ──────────────────────────────────────────────────────────────
  window._analookAuth = {
    get user() { return _session?.user ?? null; },

    /** 返回当前 access_token（用于 Authorization: Bearer 头） */
    getToken() { return _session?.access_token ?? null; },

    /** 显示登录弹窗 */
    showModal() { _openModal(); },

    /** 主动登出 */
    async logout() {
      await sb.auth.signOut();
    },
  };

  // ── UI 更新 ───────────────────────────────────────────────────────────────
  function _updateUI(user) {
    const btn      = document.getElementById('auth-btn');
    const userArea = document.getElementById('auth-user-area');
    const avatar   = document.getElementById('auth-avatar');
    const credit   = document.getElementById('credits-display');
    const emailEl  = document.getElementById('auth-dropdown-email');

    if (!btn) return;

    if (user) {
      // 已登录：隐藏登录按钮，显示用户区域
      btn.classList.add('hidden');
      if (userArea) userArea.classList.remove('hidden');
      if (avatar) {
        const initials = (user.email || '?')[0].toUpperCase();
        avatar.textContent = initials;
      }
      if (emailEl) emailEl.textContent = user.email;
      // 异步拉取积分
      _fetchCredits();
    } else {
      // 未登录：显示登录按钮
      btn.classList.remove('hidden');
      if (userArea) userArea.classList.add('hidden');
      if (credit) credit.classList.add('hidden');
    }
  }

  async function _fetchCredits() {
    const token = _session?.access_token;
    if (!token) return;
    try {
      const res = await fetch('/api/me', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) return;
      const profile = await res.json();
      const el = document.getElementById('credits-display');
      if (el) {
        el.classList.remove('hidden');
        el.textContent = `⚡ ${profile.credits_balance ?? 0} 积分`;
        el.title = `套餐：${profile.plan_type}  已用：${profile.credits_used ?? 0}`;
      }
    } catch {}
  }

  // ── Modal ─────────────────────────────────────────────────────────────────
  function _openModal(tab = 'login') {
    const modal = document.getElementById('auth-modal');
    if (modal) {
      modal.classList.remove('hidden');
      _switchAuthTab(tab);
    }
  }

  function _closeModal() {
    const modal = document.getElementById('auth-modal');
    if (modal) modal.classList.add('hidden');
    _clearAuthError();
  }

  function _switchAuthTab(tab) {
    document.getElementById('auth-tab-login')?.classList.toggle('hidden', tab !== 'login');
    document.getElementById('auth-tab-signup')?.classList.toggle('hidden', tab !== 'signup');
    document.getElementById('auth-tab-btn-login')?.classList.toggle('text-blue-400', tab === 'login');
    document.getElementById('auth-tab-btn-signup')?.classList.toggle('text-blue-400', tab === 'signup');
  }

  function _setAuthError(msg) {
    const el = document.getElementById('auth-error');
    if (el) { el.textContent = msg; el.classList.remove('hidden'); }
  }

  function _clearAuthError() {
    const el = document.getElementById('auth-error');
    if (el) { el.textContent = ''; el.classList.add('hidden'); }
  }

  function _setLoading(loading) {
    ['auth-login-btn', 'auth-signup-btn', 'auth-google-btn', 'auth-github-btn'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.disabled = loading;
    });
  }

  // ── 事件绑定（DOM 已 ready 则立即执行，否则等待）────────────────────────
  function _bindEvents() {
    // 打开弹窗
    document.getElementById('auth-btn')?.addEventListener('click', () => _openModal('login'));

    // 关闭弹窗（点背景或 ✕）
    document.getElementById('auth-modal')?.addEventListener('click', e => {
      if (e.target.id === 'auth-modal') _closeModal();
    });
    document.getElementById('auth-close-btn')?.addEventListener('click', _closeModal);

    // Tab 切换
    document.getElementById('auth-tab-btn-login')?.addEventListener('click', () => _switchAuthTab('login'));
    document.getElementById('auth-tab-btn-signup')?.addEventListener('click', () => _switchAuthTab('signup'));

    // 登录
    document.getElementById('auth-login-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const email = document.getElementById('auth-email')?.value?.trim();
      const pass  = document.getElementById('auth-password')?.value;
      if (!email || !pass) return _setAuthError('请输入邮箱和密码');
      _setLoading(true);
      const { error } = await sb.auth.signInWithPassword({ email, password: pass });
      _setLoading(false);
      if (error) return _setAuthError(error.message);
      _closeModal();
    });

    // 注册
    document.getElementById('auth-signup-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const email = document.getElementById('auth-signup-email')?.value?.trim();
      const pass  = document.getElementById('auth-signup-password')?.value;
      if (!email || !pass) return _setAuthError('请输入邮箱和密码');
      if (pass.length < 6) return _setAuthError('密码至少 6 位');
      _setLoading(true);
      const { error } = await sb.auth.signUp({ email, password: pass });
      _setLoading(false);
      if (error) return _setAuthError(error.message);
      _setAuthError('✅ 注册成功！请查收验证邮件后登录');
      _switchAuthTab('login');
    });

    // Google OAuth
    document.getElementById('auth-google-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const { error } = await sb.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: 'https://www.analook.com' },
      });
      if (error) _setAuthError(error.message);
    });

    // GitHub OAuth
    document.getElementById('auth-github-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const { error } = await sb.auth.signInWithOAuth({
        provider: 'github',
        options: { redirectTo: 'https://www.analook.com' },
      });
      if (error) _setAuthError(error.message);
    });

    // 头像点击：切换下拉菜单
    document.getElementById('auth-avatar')?.addEventListener('click', (e) => {
      e.stopPropagation();
      const dropdown = document.getElementById('auth-dropdown');
      if (dropdown) dropdown.classList.toggle('hidden');
    });

    // 点击页面其他区域关闭下拉
    document.addEventListener('click', () => {
      document.getElementById('auth-dropdown')?.classList.add('hidden');
    });

    // 登出按钮
    document.getElementById('auth-logout-btn')?.addEventListener('click', async () => {
      await sb.auth.signOut();
      document.getElementById('auth-dropdown')?.classList.add('hidden');
    });
  }

  // DOMContentLoaded 可能已经触发（async IIFE 加载 SDK 有延迟），直接判断
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _bindEvents);
  } else {
    _bindEvents();
  }

  // ── 动态加载脚本 ──────────────────────────────────────────────────────────
  function _loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) return resolve();
      const s = document.createElement('script');
      s.src = src; s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
  }
})();
