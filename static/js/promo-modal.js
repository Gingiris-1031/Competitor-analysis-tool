/**
 * promo-modal.js — Promo code redemption modal
 *
 * Two entry points:
 *  1. "Redeem Code" button in the auth dropdown (manual, any time)
 *  2. Auto-shown once after referral-modal completes (registration flow)
 *
 * Requires: window._analookAuth.getToken() (from auth.js)
 */
(function () {
    'use strict';
    if (window._analookPromoBootstrapped) return;
    window._analookPromoBootstrapped = true;

    const STORAGE_KEY = 'analook_promo_shown_v1';

    // ── Core redeem logic ─────────────────────────────────────────────
    async function redeemCode(code) {
        const token = window._analookAuth?.getToken?.();
        if (!token) throw new Error('Not authenticated');

        const resp = await fetch('/api/redeem', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ code }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            throw new Error(data.error || 'Redemption failed');
        }
        return data; // { ok, credits_added, new_balance }
    }

    // ── Modal controller ──────────────────────────────────────────────
    function showPromoModal() {
        const modal = document.getElementById('promo-modal');
        const input = document.getElementById('promo-code-input');
        const submitBtn = document.getElementById('promo-submit-btn');
        const errEl = document.getElementById('promo-error');
        const successEl = document.getElementById('promo-success');
        const closeBtn = document.getElementById('promo-close-btn');
        if (!modal) return;

        // Reset state
        if (input) { input.value = ''; input.disabled = false; }
        if (errEl) { errEl.textContent = ''; errEl.classList.add('hidden'); }
        if (successEl) { successEl.textContent = ''; successEl.classList.add('hidden'); }
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Redeem'; }

        modal.classList.remove('hidden');

        // Auto-uppercase input
        input?.addEventListener('input', () => {
            const pos = input.selectionStart;
            input.value = input.value.toUpperCase();
            input.setSelectionRange(pos, pos);
        });

        // Enter key
        input?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') submitBtn?.click();
        });

        // Submit
        submitBtn?.addEventListener('click', async () => {
            const code = (input?.value || '').trim().toUpperCase();
            if (!code) {
                errEl.textContent = 'Please enter a code.';
                errEl.classList.remove('hidden');
                return;
            }
            submitBtn.disabled = true;
            submitBtn.textContent = 'Redeeming…';
            errEl.classList.add('hidden');
            successEl.classList.add('hidden');

            try {
                const result = await redeemCode(code);
                successEl.textContent = `🎉 +${result.credits_added} credits added! New balance: ${result.new_balance}`;
                successEl.classList.remove('hidden');
                input.disabled = true;
                submitBtn.textContent = 'Done ✓';
                // Update credits display in navbar
                const creditsEl = document.getElementById('credits-display');
                if (creditsEl) {
                    creditsEl.textContent = `⚡ ${result.new_balance} Credits`;
                }
                // Auto-close after 2.5s
                setTimeout(() => closeModal(), 2500);
            } catch (err) {
                let msg = err.message || 'Something went wrong';
                if (msg.includes('ALREADY_REDEEMED')) msg = 'You\'ve already used this code.';
                if (msg.includes('INVALID_CODE')) msg = 'Invalid code. Check the spelling and try again.';
                if (msg.includes('CODE_EXHAUSTED')) msg = 'This code has reached its usage limit.';
                errEl.textContent = msg;
                errEl.classList.remove('hidden');
                submitBtn.disabled = false;
                submitBtn.textContent = 'Redeem';
            }
        }, { once: true });

        closeBtn?.addEventListener('click', closeModal, { once: true });
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        }, { once: true });
    }

    function closeModal() {
        const modal = document.getElementById('promo-modal');
        if (modal) modal.classList.add('hidden');
    }

    // ── Entry point 1: dropdown button ────────────────────────────────
    function bindDropdownButton() {
        const btn = document.getElementById('redeem-code-btn');
        if (!btn) return;
        btn.addEventListener('click', () => {
            // Close dropdown first
            document.getElementById('auth-dropdown')?.classList.add('hidden');
            showPromoModal();
        });
    }

    // ── Entry point 2: auto-show once after referral modal completes ──
    // We hook into window._analookReferralDone becoming true.
    function watchForReferralCompletion() {
        // Skip if user already saw the promo modal this session or before
        if (sessionStorage.getItem(STORAGE_KEY)) return;

        let checks = 0;
        const timer = setInterval(() => {
            checks++;
            if (window._analookReferralDone) {
                clearInterval(timer);
                // Mark so we don't show again this session
                sessionStorage.setItem(STORAGE_KEY, '1');
                // Small delay after referral modal closes
                setTimeout(() => {
                    const token = window._analookAuth?.getToken?.();
                    if (token) showPromoModal();
                }, 600);
            }
            if (checks > 60) clearInterval(timer); // give up after 30s
        }, 500);
    }

    // ── Bootstrap ─────────────────────────────────────────────────────
    function bootstrap() {
        bindDropdownButton();
        // Only watch for referral completion if not already shown
        if (!sessionStorage.getItem(STORAGE_KEY)) {
            watchForReferralCompletion();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootstrap);
    } else {
        bootstrap();
    }
})();
