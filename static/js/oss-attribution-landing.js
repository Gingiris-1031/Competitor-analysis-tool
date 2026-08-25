(function () {
  const isZh = document.documentElement.lang.toLowerCase().startsWith('zh');
  const form = document.getElementById('repo-form');
  const input = document.getElementById('repo-input');
  const error = document.getElementById('repo-error');

  function capture(event, properties) {
    window.analookTrack?.(event, Object.assign({ landing_lang: isZh ? 'zh' : 'en' }, properties || {}));
  }

  function normalizeRepo(raw) {
    const value = raw.trim().replace(/^git@github\.com:/i, 'https://github.com/');
    let candidate;
    if (/^[\w.-]+\/[\w.-]+(?:\.git)?$/i.test(value)) {
      candidate = `https://github.com/${value}`;
    } else if (/^github\.com\//i.test(value)) {
      candidate = `https://${value}`;
    } else {
      candidate = /^https?:\/\//i.test(value) ? value : `https://${value}`;
    }
    try {
      const url = new URL(candidate);
      const parts = url.pathname.replace(/\.git$/, '').split('/').filter(Boolean);
      if (!/(^|\.)github\.com$/i.test(url.hostname) || parts.length < 2) return null;
      return `https://github.com/${parts[0]}/${parts[1]}`;
    } catch (_) {
      return null;
    }
  }

  function currentRepo() {
    const params = new URLSearchParams(window.location.search);
    return normalizeRepo(params.get('repo') || params.get('oss_repo') || '');
  }

  function continuationUrl(path, campaign, repo) {
    const url = new URL(path, window.location.origin);
    url.searchParams.set('utm_source', 'oss_attribution');
    url.searchParams.set('utm_medium', 'product');
    url.searchParams.set('utm_campaign', campaign);
    if (repo) url.searchParams.set('oss_repo', repo);
    return url.pathname + url.search;
  }

  function syncRepoContext(repo) {
    if (!repo) return;
    input.value = repo.replace(/^https:\/\/github\.com\//i, '');
    document.querySelectorAll('.faq-action').forEach(function (link) {
      const current = new URL(link.href, window.location.origin);
      link.href = continuationUrl(current.pathname, 'faq_next_step', repo);
    });
    document.querySelectorAll('a.lang').forEach(function (link) {
      const url = new URL(link.href, window.location.origin);
      url.searchParams.set('oss_repo', repo);
      link.href = url.pathname + url.search;
    });
  }

  const initialRepo = currentRepo();
  syncRepoContext(initialRepo);
  capture('oss_lp_viewed', initialRepo ? { repo_url: initialRepo } : {});
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
    syncRepoContext(repo);
    capture('oss_repo_submitted', { repo_url: repo });
    const destination = isZh ? '/zh/' : '/';
    window.location.href = `${destination}?oss_repo=${encodeURIComponent(repo)}&utm_source=oss_attribution&utm_medium=product&utm_campaign=oss_growth`;
  });
})();
