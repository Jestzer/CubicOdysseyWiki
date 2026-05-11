// Global search on the homepage. Reads assets/data.json and renders matches
// into #results as the user types. Gracefully degrades if file:// blocks the
// JSON fetch (e.g. Chromium without --allow-file-access-from-files).

(function () {
    const input = document.getElementById('globalSearch');
    const results = document.getElementById('results');
    if (!input || !results) return;

    let manifest = null;
    let fetchPromise = null;

    function ensure() {
        if (fetchPromise) return fetchPromise;
        fetchPromise = fetch('assets/data.json')
            .then(r => r.ok ? r.json() : Promise.reject(r.status))
            .then(data => { manifest = data; })
            .catch(err => {
                input.disabled = true;
                input.placeholder = 'Search disabled — open this wiki via http://, or use category links below.';
                results.innerHTML = '<div class="note"><strong>Note:</strong> your browser blocked <code>fetch(\'assets/data.json\')</code> over <code>file://</code>. The site works fully without search — browse by category, or serve the directory: <code>python3 -m http.server</code> inside the wiki folder, then visit <code>http://localhost:8000</code>.</div>';
            });
        return fetchPromise;
    }

    function rank(entry, q, qLow) {
        const name = entry.name.toLowerCase();
        const id = entry.id.toLowerCase();
        let score = 0;
        if (name === qLow) score = 1000;
        else if (name.startsWith(qLow)) score = 500;
        else if (name.includes(qLow)) score = 200;
        else if (id.includes(qLow)) score = 100;
        else return -1;
        // bonus for short names (so 'iron' matches Iron before Iron Ingot)
        score -= name.length * 0.1;
        return score;
    }

    function render(q) {
        if (!manifest) return;
        if (!q) {
            results.innerHTML = '';
            return;
        }
        const qLow = q.toLowerCase();
        const matches = [];
        for (const e of manifest) {
            const s = rank(e, q, qLow);
            if (s >= 0) matches.push({ entry: e, score: s });
        }
        matches.sort((a, b) => b.score - a.score);
        const top = matches.slice(0, 25);
        if (!top.length) {
            results.innerHTML = `<p class="empty">No matches for "${q}".</p>`;
            return;
        }
        const html = ['<ul>'];
        for (const { entry } of top) {
            const icon = entry.icon ? `<img src="${entry.icon}" alt="">`
                                    : `<div class="tier tier-${entry.tier}" style="width:36px;height:36px;display:flex;align-items:center;justify-content:center">${entry.name.slice(0,2).toUpperCase()}</div>`;
            html.push(`<li onclick="location.href='${entry.url}'">
                ${icon}
                <div><a href="${entry.url}">${entry.name}</a> <span class="tier tier-${entry.tier}">T${entry.tier}</span><br><span class="cat mono">${entry.id}</span></div>
                <span class="cat">${entry.category}</span>
            </li>`);
        }
        html.push('</ul>');
        results.innerHTML = html.join('');
    }

    input.addEventListener('focus', ensure);
    input.addEventListener('input', e => {
        ensure().then(() => render(e.target.value.trim()));
    });
    // If the user is already typing on load (e.g. browser autofill), pick it up.
    if (input.value) ensure().then(() => render(input.value.trim()));
})();
