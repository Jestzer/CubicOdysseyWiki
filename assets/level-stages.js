// Level-aware stages for the Guides pages. Persists the user's input per
// skill in localStorage so the same level shows up on every guide.
//
// HTML contract per page:
//   <div class="level-picker" data-skill="mining|trading|crafting">
//     <label>Your <skill> level: <input type="number" min="1" max="60"></label>
//     <span class="right-now"></span>
//   </div>
//   <div class="stages">
//     <article class="stage" data-min="1"  data-max="9"  data-tagline="…">…</article>
//     <article class="stage" data-min="10" data-max="19" data-tagline="…">…</article>
//     …
//   </div>
//
// Optional: any element with [data-skill-min] becomes `.locked` when the
// user's level is below the threshold (used by the Motherboards recipe
// table to grey out tier-4 crafts you can't make yet).

(function () {
    const picker = document.querySelector('.level-picker');
    if (!picker) return;

    const skill = picker.dataset.skill || 'mining';
    const input = picker.querySelector('input[type="number"]');
    const callout = picker.querySelector('.right-now');
    const key = `co.wiki.skill.${skill}`;

    // Restore previous level if present
    const saved = parseInt(localStorage.getItem(key) || '', 10);
    if (Number.isFinite(saved) && saved > 0) input.value = saved;

    function apply() {
        const lvl = Math.max(1, Math.min(99, parseInt(input.value, 10) || 1));
        if (String(lvl) !== input.value) input.value = lvl;
        try { localStorage.setItem(key, String(lvl)); } catch (_) {}

        const stages = document.querySelectorAll('.stage');
        let activeStage = null;
        stages.forEach(s => {
            const min = parseInt(s.dataset.min, 10);
            const max = parseInt(s.dataset.max || '999', 10);
            const isActive = lvl >= min && lvl <= max;
            s.classList.toggle('active', isActive);
            if (isActive) activeStage = s;
        });

        if (callout) {
            if (activeStage) {
                const tagline = activeStage.dataset.tagline || '';
                callout.innerHTML = `<strong>At level ${lvl}:</strong> ${tagline}`;
            } else {
                callout.textContent = `Level ${lvl} — no matching stage.`;
            }
        }

        document.querySelectorAll('[data-skill-min]').forEach(el => {
            const need = parseInt(el.dataset.skillMin, 10);
            el.classList.toggle('locked', Number.isFinite(need) && lvl < need);
        });
    }

    input.addEventListener('input', apply);
    apply();
})();
