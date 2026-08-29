// i18n: zh pages set window._ANALOOK_LANG='zh' before loading shared JS.
var _LANG_ZH = (typeof window !== 'undefined') && (window._ANALOOK_LANG === 'zh' || location.pathname.startsWith('/zh'));
var _t = _t || function (en, zh) { return _LANG_ZH ? zh : en; };
/**
 * referral-modal.js — first-time-authenticated referral source survey
 *
 * Fires once per user. Polls /api/me; if the user is authenticated and
 * `referral_source` is null, asks how they found Analook. It must never
 * block the first report or trap a user in a modal: users may defer it and
 * return later.
 *
 * Include via:  <script src="/js/referral-modal.js" defer></script>
 * No setup needed — it self-bootstraps.
 *
 * Required global: window._analookAuth.getToken() (set up by auth.js).
 */
(function () {
    'use strict';
    if (window._analookReferralBootstrapped) return;
    window._analookReferralBootstrapped = true;

    // ── Styles ────────────────────────────────────────────────────────
    const css = `
      #analook-ref-overlay {
        position: fixed; inset: 0; z-index: 99999;
        background: rgba(13,13,15,0.72);
        backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
        display: flex; align-items: center; justify-content: center;
        padding: 24px;
        animation: anaRefIn 0.22s ease-out;
      }
      @keyframes anaRefIn { from { opacity: 0 } to { opacity: 1 } }
      #analook-ref-overlay * { box-sizing: border-box; font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
      .ana-ref-card {
        max-width: 480px; width: 100%;
        background: #16161A;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 32px 30px 26px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        color: #F5F1EB;
      }
      .ana-ref-stripe {
        height: 3px; border-radius: 2px; width: 56px; margin-bottom: 20px;
        background: linear-gradient(90deg, #FB923C, #FDBA74);
      }
      .ana-ref-card h2 {
        font-family: "Instrument Serif", Georgia, serif;
        font-style: italic; font-size: 30px; line-height: 1.15;
        margin: 0 0 8px; font-weight: 400;
        letter-spacing: -0.02em;
      }
      .ana-ref-card p.sub {
        color: rgba(245,241,235,0.65); font-size: 14px;
        margin: 0 0 22px; line-height: 1.55;
      }
      .ana-ref-opts {
        display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
        margin-bottom: 14px;
      }
      .ana-ref-opt {
        background: #1C1C21;
        border: 1px solid rgba(255,255,255,0.08);
        color: #F5F1EB;
        font-size: 14px; font-weight: 500;
        padding: 12px 14px;
        border-radius: 10px;
        cursor: pointer; text-align: left;
        display: flex; align-items: center; gap: 10px;
        transition: border-color .15s, background .15s;
      }
      .ana-ref-opt:hover { border-color: rgba(251,146,60,0.5); background: #1F1F25; }
      .ana-ref-opt.active {
        border-color: #FB923C; background: rgba(251,146,60,0.08);
      }
      .ana-ref-opt .ico { font-size: 16px; width: 18px; text-align: center; }
      .ana-ref-other {
        display: none;
        margin: 6px 0 14px;
      }
      .ana-ref-other.visible { display: block; }
      .ana-ref-other input {
        width: 100%;
        background: #1C1C21;
        border: 1px solid rgba(255,255,255,0.10);
        color: #F5F1EB;
        font-size: 14px;
        padding: 10px 12px; border-radius: 9px;
        outline: none;
        transition: border-color .15s;
      }
      .ana-ref-other input:focus { border-color: #FB923C; }
      .ana-ref-cta {
        width: 100%;
        background: #FB923C; color: #0D0D0F;
        font-weight: 600; font-size: 14px;
        padding: 12px; border: none; border-radius: 10px;
        cursor: pointer; margin-top: 4px;
        transition: background .15s, transform .1s;
      }
      .ana-ref-cta:hover:not(:disabled) { background: #FDBA74; }
      .ana-ref-cta:active:not(:disabled) { transform: translateY(1px); }
      .ana-ref-cta:disabled { opacity: 0.5; cursor: not-allowed; }
      .ana-ref-skip {
        display:block; width:100%; margin-top:10px; padding:7px;
        border:0; background:transparent; color:rgba(245,241,235,0.58);
        font-size:12px; cursor:pointer;
      }
      .ana-ref-skip:hover { color:#F5F1EB; }
      .ana-ref-err {
        color: #f87171; font-size: 12.5px; margin-top: 10px;
        min-height: 16px;
      }
      .ana-ref-footer {
        margin-top: 18px;
        font-size: 11px; color: rgba(245,241,235,0.40);
        text-align: center; letter-spacing: 0.02em;
      }
      @media (max-width: 480px) {
        .ana-ref-opts { grid-template-columns: 1fr; }
        .ana-ref-card { padding: 28px 22px 22px; }
        .ana-ref-card h2 { font-size: 26px; }
      }
    `;

    // ── Build & show modal ─────────────────────────────────────────────
    function showModal() {
        if (document.getElementById('analook-ref-overlay')) return;

        const style = document.createElement('style');
        style.textContent = css;
        document.head.appendChild(style);

        const overlay = document.createElement('div');
        overlay.id = 'analook-ref-overlay';
        overlay.innerHTML = `
          <div class="ana-ref-card" role="dialog" aria-modal="true" aria-labelledby="ana-ref-title">
            <div class="ana-ref-stripe"></div>
            <h2 id="ana-ref-title">${_t('How did you <em style="color:#FB923C">find</em> Analook?', '你是从哪里<em style="color:#FB923C">发现</em> Analook 的？')}</h2>
            <p class="sub">${_t("One question that helps us attribute growth — so we know which channel to invest in next.", "一个问题，帮我们做归因 — 这样下次知道在哪个渠道再投资。")}</p>

            <div class="ana-ref-opts" role="radiogroup" aria-label="Referral source">
              <button class="ana-ref-opt" data-source="twitter"        role="radio" aria-checked="false"><span class="ico">𝕏</span><span>Twitter / X</span></button>
              <button class="ana-ref-opt" data-source="linkedin"       role="radio" aria-checked="false"><span class="ico" style="color:#0a66c2">in</span><span>LinkedIn</span></button>
              <button class="ana-ref-opt" data-source="google_search"  role="radio" aria-checked="false"><span class="ico">🔎</span><span>${_t('Google Search', 'Google 搜索')}</span></button>
              <button class="ana-ref-opt" data-source="geo"            role="radio" aria-checked="false"><span class="ico">🤖</span><span>${_t('AI Search (ChatGPT, Perplexity, Claude)', 'AI 搜索（ChatGPT、Perplexity、Claude）')}</span></button>
              <button class="ana-ref-opt" data-source="referral"       role="radio" aria-checked="false"><span class="ico">👥</span><span>${_t("Friend / Word of mouth", "朋友推荐 / Word of mouth")}</span></button>
              <button class="ana-ref-opt" data-source="other"          role="radio" aria-checked="false"><span class="ico">✏️</span><span>${_t('Other (type in)', '其他（请填写）')}</span></button>
            </div>

            <div class="ana-ref-other" id="ana-ref-other-wrap">
              <input type="text" id="ana-ref-other-input" placeholder="${_t('e.g. Reddit, Dev.to article, podcast...', '例如 Reddit、公众号、播客……')}" maxlength="200">
            </div>

            <button class="ana-ref-cta" id="ana-ref-submit" disabled>${_t('Continue →', '继续 →')}</button>
            <button type="button" class="ana-ref-skip" id="ana-ref-skip">${_t('Not now', '暂不填写')}</button>
            <div class="ana-ref-err" id="ana-ref-err"></div>
            <div class="ana-ref-footer">${_t('Optional · anonymous to other users · only Iris sees the aggregate', '可选填写 · 对其他用户匿名 · 仅用于汇总渠道效果')}</div>
          </div>
        `;
        document.body.appendChild(overlay);

        let chosen = null;
        const opts = overlay.querySelectorAll('.ana-ref-opt');
        const otherWrap = overlay.querySelector('#ana-ref-other-wrap');
        const otherInput = overlay.querySelector('#ana-ref-other-input');
        const submit = overlay.querySelector('#ana-ref-submit');
        const skip = overlay.querySelector('#ana-ref-skip');
        const errEl = overlay.querySelector('#ana-ref-err');

        function dismiss(snooze = false) {
            if (snooze) {
                // Avoid repeatedly interrupting a user who intentionally
                // deferred the question. The server remains authoritative
                // once they submit a source.
                try { localStorage.setItem('analook_referral_snooze_until', String(Date.now() + 7 * 24 * 60 * 60 * 1000)); } catch (_) {}
            }
            overlay.style.transition = 'opacity 0.18s ease-in';
            overlay.style.opacity = '0';
            setTimeout(() => overlay.remove(), 200);
            document.removeEventListener('keydown', onEscape);
            window._analookReferralDone = true;
        }

        skip?.addEventListener('click', () => dismiss(true));
        overlay.addEventListener('click', (event) => { if (event.target === overlay) dismiss(true); });
        const onEscape = (event) => {
            if (event.key === 'Escape') {
                dismiss(true);
                document.removeEventListener('keydown', onEscape);
            }
        };
        document.addEventListener('keydown', onEscape);

        function refreshSubmitEnabled() {
            if (!chosen) { submit.disabled = true; return; }
            if (chosen === 'other' && !otherInput.value.trim()) {
                submit.disabled = true; return;
            }
            submit.disabled = false;
        }

        opts.forEach(el => {
            el.addEventListener('click', () => {
                opts.forEach(o => { o.classList.remove('active'); o.setAttribute('aria-checked', 'false'); });
                el.classList.add('active');
                el.setAttribute('aria-checked', 'true');
                chosen = el.getAttribute('data-source');
                if (chosen === 'other') {
                    otherWrap.classList.add('visible');
                    setTimeout(() => otherInput.focus(), 50);
                } else {
                    otherWrap.classList.remove('visible');
                }
                refreshSubmitEnabled();
            });
        });
        otherInput.addEventListener('input', refreshSubmitEnabled);

        submit.addEventListener('click', async () => {
            if (submit.disabled) return;
            submit.disabled = true;
            submit.textContent = _t('Saving…', '保存中…');
            errEl.textContent = '';

            const token = window._analookAuth?.getToken?.();
            if (!token) {
                errEl.textContent = _t('Please sign in again.', '请重新登录。');
                submit.disabled = false; submit.textContent = _t('Continue →', '继续 →');
                return;
            }

            try {
                const body = { source: chosen };
                if (chosen === 'other' || otherInput.value.trim()) {
                    body.other = otherInput.value.trim();
                }
                const r = await fetch('/api/profile/referral', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                    body: JSON.stringify(body),
                });
                const d = await r.json();
                if (!r.ok) {
                    errEl.textContent = d.error || _t('Save failed', '保存失败');
                    submit.disabled = false; submit.textContent = _t('Continue →', '继续 →');
                    return;
                }
                // Success: dismiss and mark the question complete.
                dismiss(false);
            } catch (e) {
                errEl.textContent = _t('Network error: ', '网络错误：') + e.message;
                submit.disabled = false; submit.textContent = _t('Continue →', '继续 →');
            }
        });
    }

    // ── Probe /api/me and decide ───────────────────────────────────────
    async function checkAndMaybeShow() {
        if (window._analookReferralDone) return;
        try {
            if (Number(localStorage.getItem('analook_referral_snooze_until') || 0) > Date.now()) return;
        } catch (_) {}
        // The first OSS report is the activation moment. Never block it with a
        // survey; ask on a later, non-OSS page instead.
        if (new URLSearchParams(window.location.search).get('oss_repo')) return;
        const token = window._analookAuth?.getToken?.();
        if (!token) return;  // not logged in — skip
        try {
            const r = await fetch('/api/me', {
                headers: { 'Authorization': `Bearer ${token}` },
            });
            if (!r.ok) return;
            const profile = await r.json();
            // If the profile doesn't have the field yet (e.g. migration not
            // run), we silently skip rather than spam the user.
            if (Object.prototype.hasOwnProperty.call(profile, 'referral_source')
                && profile.referral_source == null) {
                showModal();
            } else {
                window._analookReferralDone = true;
            }
        } catch (_) {
            // network blip — try again next page load
        }
    }

    // Run after auth.js has had a chance to set up window._analookAuth.
    // We poll briefly because auth.js might init asynchronously.
    function bootstrap() {
        let tries = 0;
        const timer = setInterval(() => {
            tries += 1;
            if (window._analookAuth) {
                clearInterval(timer);
                checkAndMaybeShow();
            } else if (tries > 20) {
                clearInterval(timer);  // give up after 5s
            }
        }, 250);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }
})();
