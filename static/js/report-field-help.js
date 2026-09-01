/* Accessible, bilingual field-help popovers for report metrics. */
(function (global) {
    'use strict';

    let activePopover = null;
    let listenersReady = false;

    function language() {
        return global._ANALOOK_LANG === 'zh' || location.pathname.startsWith('/zh') ? 'zh' : 'en';
    }

    function localized(value, lang) {
        return value && (value[lang] || value.en) || '';
    }

    function closeActive() {
        if (!activePopover) return;
        activePopover.hidden = true;
        activePopover.previousElementSibling?.setAttribute('aria-expanded', 'false');
        activePopover = null;
    }

    function buildPopover(key, entry, lang) {
        const popover = document.createElement('span');
        popover.className = 'report-field-popover';
        popover.id = `report-field-help-${key}`;
        popover.setAttribute('role', 'tooltip');
        popover.hidden = true;

        const title = document.createElement('strong');
        title.className = 'report-field-popover-title';
        title.textContent = localized(entry.title, lang);

        const description = document.createElement('span');
        description.className = 'report-field-popover-copy';
        description.textContent = localized(entry.description, lang);

        const caveat = document.createElement('span');
        caveat.className = 'report-field-popover-caveat';
        caveat.textContent = localized(entry.caveat, lang);

        const source = document.createElement('span');
        source.className = 'report-field-popover-source';
        source.textContent = `${lang === 'zh' ? '数据来源' : 'Source'}: ${entry.source}`;

        popover.append(title, description, caveat, source);
        return popover;
    }

    function enhance(root) {
        const glossary = global.AnalookReportGlossary || {};
        const lang = language();
        (root || document).querySelectorAll('[data-field-help]').forEach((label) => {
            if (label.dataset.fieldHelpReady === 'true') return;
            const key = label.dataset.fieldHelp;
            const entry = glossary[key];
            if (!entry) return;

            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'report-field-help-button';
            button.textContent = '?';
            button.setAttribute('aria-label', `${lang === 'zh' ? '了解' : 'Explain'} ${localized(entry.title, lang)}`);
            button.setAttribute('aria-expanded', 'false');
            button.setAttribute('aria-describedby', `report-field-help-${key}`);

            const popover = buildPopover(key, entry, lang);
            button.addEventListener('click', (event) => {
                event.stopPropagation();
                const opening = popover.hidden;
                closeActive();
                if (opening) {
                    popover.hidden = false;
                    button.setAttribute('aria-expanded', 'true');
                    activePopover = popover;
                    global.analookTrack?.('report_field_help_opened', {
                        help_key: key,
                        report_lang: lang,
                    });
                }
            });

            label.classList.add('report-field-label');
            label.append(button, popover);
            label.dataset.fieldHelpReady = 'true';
        });

        if (!listenersReady) {
            document.addEventListener('click', closeActive);
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') closeActive();
            });
            listenersReady = true;
        }
    }

    global.AnalookFieldHelp = Object.freeze({ enhance, close: closeActive });
})(window);
