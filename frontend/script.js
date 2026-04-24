'use strict';

// When opened as a local file (file://) point directly at the backend.
// When served by FastAPI, use the same origin.
const API_BASE =
    window.location.protocol === 'file:'
        ? 'http://localhost:8000'
        : window.location.origin;

const form       = document.getElementById('analyze-form');
const urlInput   = document.getElementById('repo-url');
const analyzeBtn = document.getElementById('analyze-btn');
const errorBanner  = document.getElementById('error-banner');
const errorMessage = document.getElementById('error-message');
const loading    = document.getElementById('loading');
const results    = document.getElementById('results');

form.addEventListener('submit', (e) => {
    e.preventDefault();
    const url = urlInput.value.trim();
    if (!url) return;
    runAnalysis(url);
});

async function runAnalysis(repoUrl) {
    setLoading(true);
    hideError();
    hideResults();

    try {
        const resp = await fetch(`${API_BASE}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo_url: repoUrl }),
        });

        const data = await resp.json();

        if (!resp.ok) {
            throw new Error(data.detail || `Server error (${resp.status})`);
        }

        renderResults(data, repoUrl);

    } catch (err) {
        if (err instanceof TypeError && err.message.toLowerCase().includes('fetch')) {
            showError(
                'Cannot reach the backend. Make sure the server is running: ' +
                'uvicorn backend.main:app --reload --port 8000'
            );
        } else {
            showError(err.message || 'An unexpected error occurred.');
        }
    } finally {
        setLoading(false);
    }
}

function renderResults(data, repoUrl) {
    // Header
    const repoPath = repoUrl.replace(/^https?:\/\/github\.com\//, '').replace(/\/$/, '');
    document.getElementById('results-repo-name').textContent = repoPath;

    const linkEl = document.getElementById('results-repo-link');
    linkEl.href = repoUrl.startsWith('http') ? repoUrl : `https://github.com/${repoUrl}`;

    const fileCount = (data.important_files || []).length;
    document.getElementById('results-meta').textContent =
        `${fileCount} file${fileCount !== 1 ? 's' : ''} analyzed`;

    // Summary
    setText('project-summary', data.project_summary, 'No summary available.');

    // Tech Stack
    const techEl = document.getElementById('tech-stack');
    techEl.innerHTML = '';
    (data.tech_stack || []).forEach((tech) => {
        const span = document.createElement('span');
        span.className = 'tag';
        span.textContent = tech;
        techEl.appendChild(span);
    });
    if (!data.tech_stack || data.tech_stack.length === 0) {
        techEl.innerHTML = '<span class="card-text">None detected</span>';
    }

    // Architecture
    setText('architecture', data.architecture, 'Not determined.');

    // Key Components
    const compEl = document.getElementById('key-components');
    compEl.innerHTML = '';
    (data.key_components || []).forEach((item) => {
        const li = document.createElement('li');
        if (item && typeof item === 'object') {
            li.innerHTML =
                `<span class="component-name">${esc(item.name || '')}</span>` +
                `<span class="component-role">${esc(item.role || '')}</span>`;
        } else {
            li.innerHTML = `<span class="component-role">${esc(String(item))}</span>`;
        }
        compEl.appendChild(li);
    });
    if (!data.key_components || data.key_components.length === 0) {
        compEl.innerHTML = '<li><span class="component-role">None identified</span></li>';
    }

    // How to Run
    const stepsEl = document.getElementById('how-to-run');
    stepsEl.innerHTML = '';
    (data.how_to_run || []).forEach((step) => {
        const li = document.createElement('li');
        li.textContent = step;
        stepsEl.appendChild(li);
    });
    if (!data.how_to_run || data.how_to_run.length === 0) {
        stepsEl.innerHTML = '<li>No run instructions could be inferred.</li>';
    }

    // Risks
    const risksEl = document.getElementById('risks');
    risksEl.innerHTML = '';
    (data.risks || []).forEach((risk) => {
        const li = document.createElement('li');
        li.textContent = risk;
        risksEl.appendChild(li);
    });
    if (!data.risks || data.risks.length === 0) {
        risksEl.innerHTML = '<li>No significant risks identified.</li>';
    }

    // Improvements
    const impEl = document.getElementById('improvements');
    impEl.innerHTML = '';
    (data.improvement_suggestions || []).forEach((item) => {
        const li = document.createElement('li');
        li.textContent = item;
        impEl.appendChild(li);
    });
    if (!data.improvement_suggestions || data.improvement_suggestions.length === 0) {
        impEl.innerHTML = '<li>No suggestions at this time.</li>';
    }

    // Important Files
    const filesEl = document.getElementById('important-files');
    filesEl.innerHTML = '';
    (data.important_files || []).forEach((file) => {
        const li = document.createElement('li');
        li.textContent = file;
        filesEl.appendChild(li);
    });
    if (!data.important_files || data.important_files.length === 0) {
        filesEl.innerHTML = '<li>None listed</li>';
    }

    // Raw JSON
    document.getElementById('raw-json').textContent = JSON.stringify(data, null, 2);

    results.classList.remove('hidden');
    results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function setText(id, value, fallback) {
    const el = document.getElementById(id);
    el.textContent = value && value.trim() ? value : fallback;
}

function setLoading(active) {
    loading.classList.toggle('hidden', !active);
    analyzeBtn.disabled = active;
    analyzeBtn.textContent = active ? 'Analyzing…' : 'Analyze';
}

function showError(msg) {
    errorMessage.textContent = msg;
    errorBanner.classList.remove('hidden');
    errorBanner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideError() {
    errorBanner.classList.add('hidden');
}

function hideResults() {
    results.classList.add('hidden');
}

function esc(str) {
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
}
