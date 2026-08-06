// i18n: zh pages set window._ANALOOK_LANG='zh' before loading shared JS.
var _LANG_ZH = (typeof window !== 'undefined') && (window._ANALOOK_LANG === 'zh' || location.pathname.startsWith('/zh'));
var _t = _t || function (en, zh) { return _LANG_ZH ? zh : en; };
/**
 * auth.js — Analook Supabase Auth 模块
 * 暴露 window._analookAuth 供 app.js 使用
 */

(async function () {
  // ── 从后端 meta 标签读取 Supabase 配置（由 index.html 注入）──────────────
  const SUPABASE_URL  = document.querySelector('meta[name="supabase-url"]')?.content  || '';
  const SUPABASE_ANON = document.querySelector('meta[name="supabase-anon"]')?.content || '';

  if (!SUPABASE_URL || !SUPABASE_ANON) {
    console.warn('[auth] Supabase config missing; auth module not started');
    window._analookAuth = { user: null, getToken: () => null, showModal: () => {} };
    return;
  }

  // ── 加载 Supabase JS SDK（CDN）──────────────────────────────────────────
  await _loadScript('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js');
  const { createClient } = window.supabase;
  const sb = createClient(SUPABASE_URL, SUPABASE_ANON);

  // ── 状态 ─────────────────────────────────────────────────────────────────
  let _session = null;
  const _AUTH_MIGRATION_NOTICE_VERSION = '2026-08-account-migration-v2';

  // ── 初始化：恢复本地 session ──────────────────────────────────────────────
  const { data: { session } } = await sb.auth.getSession();
  _session = session;
  // 等 DOM ready 后再更新 UI（按钮/头像元素可能还没渲染）
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => _updateUI(session?.user ?? null));
  } else {
    _updateUI(session?.user ?? null);
  }
  if (session?.user) _sendFirstTouch();

  // 监听 Auth 状态变化（登录 / 登出 / token 刷新）
  sb.auth.onAuthStateChange((_event, newSession) => {
    _session = newSession;
    _updateUI(newSession?.user ?? null);
    // 新登录/注册：上报首次触点归因（服务端 write-once，只填 NULL）
    if (newSession?.user) _sendFirstTouch();
    if (newSession?.user && _event === 'SIGNED_IN') _showAccountMigrationNotice(newSession.user, true);
    // 登录/登出切换后，重新从服务端拉历史
    if (typeof window.syncServerHistory === 'function') {
      window.syncServerHistory();
    }
  });

  // ── 首次触点归因上报 ──────────────────────────────────────────────────────
  // localStorage 里由 attribution.js 锁定的首次 utm/referrer/landing，在用户
  // 鉴权后 POST 一次。_ft_sent 标记防止每次 pageview 重复请求；服务端 write-once
  // 保证即使多设备登录也只记录首次注册时的来源。
  async function _sendFirstTouch() {
    try {
      const token = _session?.access_token;
      if (!token) return;
      if (localStorage.getItem('_analook_ft_sent')) return;
      const ft = window._analookAttribution?.getFirstTouch?.();
      if (!ft) { localStorage.setItem('_analook_ft_sent', '1'); return; } // nothing to send
      const res = await fetch('/api/profile/attribution', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify(ft),
      });
      if (res.ok) localStorage.setItem('_analook_ft_sent', '1');
    } catch (e) {
      // best-effort — never block auth UX
    }
  }

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

    /** Force-refresh the nav credits pill. Used after a Polar webhook
     *  redirect or after a manual grant — keeps the formatting logic
     *  in one place (here) so callers can't drift back to "⚡ N 积分". */
    refreshCredits() { return _fetchCredits(); },
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
      _showAccountMigrationNotice(user, false);
    } else {
      // 未登录：显示登录按钮
      btn.classList.remove('hidden');
      if (userArea) userArea.classList.add('hidden');
      if (credit) credit.classList.add('hidden');
    }
  }

  // Account migration notice: shown as a lightweight banner whenever a user
  // is signed in, plus one acknowledgement dialog for each new sign-in.
  // It is intentionally informational while Supabase remains live: credits,
  // reports, and the current session remain available during the transition.
  function _showAccountMigrationNotice(user, forceDialog) {
    if (!user) return;
    const isZh = _LANG_ZH;
    if (!document.getElementById('account-migration-banner')) {
      const banner = document.createElement('div');
      banner.id = 'account-migration-banner';
      banner.setAttribute('role', 'status');
      banner.className = 'fixed inset-x-0 top-0 z-[60] border-b border-amber-300/35 bg-amber-50 px-4 py-2 text-center text-sm text-amber-950 shadow-sm';
      banner.innerHTML = isZh
        ? '<strong>账户系统升级中</strong>：你的报告和积分安全无虞；后续可能需要重新登录或重设密码。'
        : '<strong>Account system upgrade in progress.</strong> Your reports and credits are safe; you may be asked to sign in again or reset your password later.';
      document.body.appendChild(banner);
    }

    const key = `${_AUTH_MIGRATION_NOTICE_VERSION}:${user.id}`;
    // Existing sessions need the same acknowledgement as a fresh sign-in.
    // Defer until the page has painted so it cannot be hidden behind the
    // authentication modal or missed while the SDK restores a session.
    if (document.getElementById('account-migration-notice-modal')) return;
    if (!forceDialog && sessionStorage.getItem(key)) return;
    sessionStorage.setItem(key, '1');
    window.setTimeout(() => {
      if (document.getElementById('account-migration-notice-modal')) return;
      const modal = document.createElement('div');
      modal.id = 'account-migration-notice-modal';
      modal.className = 'fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 p-4';
      modal.innerHTML = `<div role="dialog" aria-modal="true" class="w-full max-w-md rounded-2xl border border-amber-200 bg-white p-6 shadow-2xl">
        <div class="mb-3 text-2xl">🔐</div>
        <h2 class="text-xl font-semibold text-slate-900">${isZh ? '账户系统升级提示' : 'Account system upgrade'}</h2>
        <p class="mt-3 text-sm leading-6 text-slate-600">${isZh
          ? '我们正在升级账户系统。你的现有报告、积分和订阅不会丢失。后续如看到提示，请使用原邮箱重新登录；邮箱密码用户可通过重设密码完成迁移，Google / GitHub 用户可直接再次授权登录。'
          : 'We are upgrading our account system. Your reports, credits, and subscription are safe. When prompted later, sign in again with the same email; password users can reset their password, and Google / GitHub users can authorize sign-in again.'}</p>
        <button type="button" class="mt-5 w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800">${isZh ? '我知道了' : 'Got it'}</button>
      </div>`;
      modal.querySelector('button')?.addEventListener('click', () => modal.remove());
      document.body.appendChild(modal);
    }, 250);
  }

  /**
   * Format credit count for the nav pill. Keeps the pill narrow even for
   * users with a manually-comped 6-figure balance:
   *   42        → "42"
   *   3,800     → "3,800"
   *   42,000    → "42K"
   *   999,880   → "999K"
   *   1,200,000 → "1.2M"
   */
  function _formatCredits(n) {
    n = Number(n) || 0;
    if (n < 1000)        return String(n);
    if (n < 10000)       return n.toLocaleString('en-US'); // 9,999
    if (n < 1_000_000)   return Math.round(n / 1000) + 'K';
    return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
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
      if (!el) return;
      el.classList.remove('hidden');
      const bal = Number(profile.credits_balance) || 0;
      const used = Number(profile.credits_used) || 0;
      const quota = Number(profile.credits_monthly_quota) || 0;
      const plan = profile.plan_type || 'free';

      el.textContent = `⚡ ${_formatCredits(bal)} credits`;
      // Tooltip carries the precise number AND the monthly-quota state so
      // a Pro user who's used 113/30 doesn't panic — they can see the
      // balance (real money) is still 999,880.
      const planLabel = plan.charAt(0).toUpperCase() + plan.slice(1);
      el.title = (
        `Balance: ${bal.toLocaleString('en-US')} credits\n` +
        `Plan: ${planLabel}\n` +
        (quota
          ? `Monthly allotment: ${used}/${quota} used this period`
          : `Used so far: ${used}`)
      );
    } catch (e) {
      // Silently ignore — credit display is non-critical; UX shouldn't
      // break if /api/me is slow.
    }
  }

  // ── Modal ─────────────────────────────────────────────────────────────────
  // Inject modal HTML dynamically if not present (pages other than index.html)
  function _ensureModal() {
    if (document.getElementById('auth-modal')) return;
    const div = document.createElement('div');
    div.innerHTML = `
      <div id="auth-modal" class="hidden fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
        <div class="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-md p-6 relative shadow-2xl">
          <button id="auth-close-btn" class="absolute top-4 right-4 text-gray-500 hover:text-gray-300 text-xl leading-none">✕</button>
          <div class="text-center mb-6">
            <span class="text-2xl font-bold text-white">Analook</span>
            <p class="text-xs text-gray-500 mt-1">Sign in to get 2 free competitor reports</p>
          </div>
          <div class="flex gap-4 border-b border-gray-700 mb-5 text-sm font-medium">
            <button id="auth-tab-btn-login" class="pb-2 text-blue-400 border-b-2 border-blue-400 -mb-px transition-colors">Sign In</button>
            <button id="auth-tab-btn-signup" class="pb-2 text-gray-400 hover:text-gray-200 transition-colors">Sign Up</button>
          </div>
          <div id="auth-error" class="hidden mb-4 text-sm text-red-400 bg-red-900/20 border border-red-800/40 rounded-lg px-3 py-2"></div>
          <div id="auth-tab-login" class="space-y-3">
            <input id="auth-email" type="email" placeholder="Email" class="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 text-sm">
            <input id="auth-password" type="password" placeholder="Password" class="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 text-sm">
            <button id="auth-login-btn" class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition-colors text-sm">Sign In</button>
          </div>
          <div id="auth-tab-signup" class="hidden space-y-3">
            <input id="auth-signup-email" type="email" placeholder="Email" class="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 text-sm">
            <input id="auth-signup-password" type="password" placeholder="Password (min 6 characters)" class="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 text-sm">
            <button id="auth-signup-btn" class="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium py-2.5 rounded-lg transition-colors text-sm">Sign Up Free — 2 reports included</button>
          </div>
          <div class="flex items-center gap-3 my-4"><div class="flex-1 h-px bg-gray-700"></div><span class="text-xs text-gray-500">or</span><div class="flex-1 h-px bg-gray-700"></div></div>
          <button id="auth-google-btn" class="w-full bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-medium py-2.5 rounded-lg transition-colors text-sm flex items-center justify-center gap-2 disabled:opacity-50">
            <svg class="w-4 h-4" viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
            Sign in with Google
          </button>
          <button id="auth-github-btn" class="w-full bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-medium py-2.5 rounded-lg transition-colors text-sm flex items-center justify-center gap-2 disabled:opacity-50 mt-2">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/></svg>
            Sign in with GitHub
          </button>
          <button id="auth-magiclink-btn" class="w-full bg-gray-800 hover:bg-gray-700 border border-gray-700 text-white font-medium py-2.5 rounded-lg transition-colors text-sm flex items-center justify-center gap-2 disabled:opacity-50 mt-2">
            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 8l9 6 9-6"/><rect x="3" y="5" width="18" height="14" rx="2"/></svg>
            Email me a magic link
          </button>
          <p class="text-center text-xs text-gray-600 mt-4">By signing in you agree to our <a href="#" class="text-gray-500 hover:text-gray-300">Terms of Service</a> and <a href="#" class="text-gray-500 hover:text-gray-300">Privacy Policy</a></p>
        </div>
      </div>`;
    document.body.appendChild(div.firstElementChild);
    // Bind handlers for the dynamically injected modal
    document.getElementById('auth-close-btn')?.addEventListener('click', _closeModal);
    document.getElementById('auth-modal')?.addEventListener('click', e => { if (e.target.id === 'auth-modal') _closeModal(); });
    document.getElementById('auth-tab-btn-login')?.addEventListener('click', () => _switchAuthTab('login'));
    document.getElementById('auth-tab-btn-signup')?.addEventListener('click', () => _switchAuthTab('signup'));
    document.getElementById('auth-login-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const email = document.getElementById('auth-email')?.value?.trim();
      const pass  = document.getElementById('auth-password')?.value;
      if (!email || !pass) return _setAuthError('Please enter email and password');
      _setLoading(true);
      const { error } = await sb.auth.signInWithPassword({ email, password: pass });
      _setLoading(false);
      if (error) return _setAuthError(error.message);
      _closeModal();
    });
    document.getElementById('auth-signup-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const email = document.getElementById('auth-signup-email')?.value?.trim();
      const pass  = document.getElementById('auth-signup-password')?.value;
      if (!email || !pass) return _setAuthError('Please enter email and password');
      if (pass.length < 6) return _setAuthError('Password must be at least 6 characters');
      _setLoading(true);
      const { error } = await sb.auth.signUp({ email, password: pass });
      _setLoading(false);
      if (error) return _setAuthError(error.message);
      _setAuthError('✅ Registration successful! Check your email to verify.');
      _switchAuthTab('login');
    });
    document.getElementById('auth-google-btn')?.addEventListener('click', async () => {
      const { error } = await sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } });
      if (error) _setAuthError(error.message);
    });
    document.getElementById('auth-github-btn')?.addEventListener('click', async () => {
      const { error } = await sb.auth.signInWithOAuth({ provider: 'github', options: { redirectTo: window.location.origin } });
      if (error) _setAuthError(error.message);
    });
    document.getElementById('auth-magiclink-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const email = (document.getElementById('auth-email')?.value
                  || document.getElementById('auth-signup-email')?.value || '').trim();
      if (!email) return _setAuthError('Enter your email above, then click "Email me a magic link"');
      _setLoading(true);
      const { error } = await sb.auth.signInWithOtp({
        email,
        options: { emailRedirectTo: window.location.origin, shouldCreateUser: true },
      });
      _setLoading(false);
      if (error) return _setAuthError(error.message);
      _setAuthError(`✅ Check ${email} — magic link sent. Click it to sign in.`);
    });
  }

  function _openModal(tab = 'login') {
    _ensureModal();
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
    // Bug fix (Iris 2026-06-18, reported by @Fuuqius on X): the visible
    // "active" indicator is the blue UNDERLINE — `border-b-2 border-blue-400
    // -mb-px` in the HTML. Previously we only toggled `text-blue-400`
    // (text color), so the underline stayed under the originally-active
    // tab and the modal looked stuck on Login even though the Signup
    // form was rendered. Now both the text color AND the underline trio
    // get toggled together.
    const _login  = document.getElementById('auth-tab-btn-login');
    const _signup = document.getElementById('auth-tab-btn-signup');
    const _ACTIVE = ['text-blue-400', 'border-b-2', 'border-blue-400', '-mb-px'];
    const _INACTIVE = ['text-[color:var(--ink-muted)]'];
    if (_login) {
      _ACTIVE.forEach(c => _login.classList.toggle(c, tab === 'login'));
      _INACTIVE.forEach(c => _login.classList.toggle(c, tab !== 'login'));
    }
    if (_signup) {
      _ACTIVE.forEach(c => _signup.classList.toggle(c, tab === 'signup'));
      _INACTIVE.forEach(c => _signup.classList.toggle(c, tab !== 'signup'));
    }
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
    ['auth-login-btn', 'auth-signup-btn', 'auth-google-btn', 'auth-github-btn', 'auth-magiclink-btn'].forEach(id => {
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
      if (!email || !pass) return _setAuthError(_t('Please enter email and password', '请输入邮箱和密码'));
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
      if (!email || !pass) return _setAuthError(_t('Please enter email and password', '请输入邮箱和密码'));
      if (pass.length < 6) return _setAuthError(_t('Password must be at least 6 characters', '密码至少 6 位'));
      _setLoading(true);
      const { error } = await sb.auth.signUp({ email, password: pass });
      _setLoading(false);
      if (error) return _setAuthError(error.message);
      _setAuthError(_t('✅ Registered! Check your email to verify, then sign in.', '✅ 注册成功！请查收验证邮件后登录'));
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

    // Email magic-link (Supabase OTP) — frictionless option for users who
    // don't want a password and don't have / want to use OAuth providers.
    document.getElementById('auth-magiclink-btn')?.addEventListener('click', async () => {
      _clearAuthError();
      const email = (document.getElementById('auth-email')?.value
                  || document.getElementById('auth-signup-email')?.value || '').trim();
      if (!email) return _setAuthError(_t('Enter your email above, then click the magic-link button', '请先填邮箱再点击「邮件登录」'));
      _setLoading(true);
      const { error } = await sb.auth.signInWithOtp({
        email,
        options: { emailRedirectTo: 'https://www.analook.com', shouldCreateUser: true },
      });
      _setLoading(false);
      if (error) return _setAuthError(error.message);
      _setAuthError(_t(`✅ Sent to ${email} — click the magic link in your inbox to sign in`, `✅ 已发送到 ${email}，请到邮箱点击魔法链接登录`));
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
