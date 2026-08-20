(function () {
  const isZh = document.documentElement.lang.toLowerCase().startsWith('zh');
  const form = document.getElementById('repo-form');
  const input = document.getElementById('repo-input');
  const error = document.getElementById('repo-error');

  function capture(event, properties) {
    if (window.posthog && typeof window.posthog.capture === 'function') {
      window.posthog.capture(event, Object.assign({ landing_lang: isZh ? 'zh' : 'en' }, properties || {}));
    }
  }

  function normalizeRepo(raw) {
    const value = raw.trim().replace(/^git@github\.com:/i, 'https://github.com/');
    const candidate = /^https?:\/\//i.test(value) ? value : `https://${value}`;
    try {
      const url = new URL(candidate);
      const parts = url.pathname.replace(/\.git$/, '').split('/').filter(Boolean);
      if (!/(^|\.)github\.com$/i.test(url.hostname) || parts.length < 2) return null;
      return `https://github.com/${parts[0]}/${parts[1]}`;
    } catch (_) {
      return null;
    }
  }

  capture('oss_lp_viewed');
  document.querySelectorAll('[data-track]').forEach(function (link) {
    link.addEventListener('click', function () { capture(link.dataset.track); });
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    const repo = normalizeRepo(input.value);
    if (!repo) {
      error.textContent = isZh ? '请输入有效的 GitHub 仓库地址，例如 github.com/calesthio/OpenMontage' : 'Enter a valid GitHub repository, for example github.com/calesthio/OpenMontage';
      input.focus();
      return;
    }
    error.textContent = '';
    capture('oss_repo_submitted', { repo_url: repo });
    const destination = isZh ? '/zh/' : '/';
    window.location.href = `${destination}?oss_repo=${encodeURIComponent(repo)}&utm_source=oss_attribution&utm_medium=product&utm_campaign=oss_growth`;
  });
})();
