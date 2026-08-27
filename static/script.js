let currentProfile = null;
let currentMatchedOpportunities = [];
let activeCategoryFilter = "All";
let currentSearchTerm = "";
let currentSortOrder = "match";

document.addEventListener("DOMContentLoaded", () => {
    initNavigationTabs();
    initProfileForm();
    initEngineToolbar();
    initNLPSearch();
    initLearningPath();
    loadProfileAndMatches();
    loadTrackerMetrics();
});

// NAVIGATION TABS
function initNavigationTabs() {
    const tabs = document.querySelectorAll(".nav-tab");
    tabs.forEach(tab => {
        tab.addEventListener("click", () => {
            tabs.forEach(t => t.classList.remove("active"));
            tab.classList.add("active");
            
            const targetId = tab.getAttribute("data-target");
            document.querySelectorAll(".tab-section").forEach(sec => sec.classList.remove("active"));
            const targetSec = document.getElementById(targetId);
            if (targetSec) targetSec.classList.add("active");
            
            if (targetId === "section-tracker") loadTrackerMetrics();
            if (targetId === "section-roadmap") loadLearningPath();
        });
    });
}

// PROFILE LOAD & MATCH ENGINE
async function loadProfileAndMatches() {
    const statusBadge = document.getElementById("userStatusBadge");
    try {
        const res = await fetch("/api/profile");
        if (res.status === 401) {
            window.location.href = "/login";
            return;
        }
        const data = await res.json();
        
        if (data.authenticated) {
            statusBadge.textContent = `● Active Student Session`;
            currentProfile = data.profile || {};
            
            // Populate profile form
            if (data.profile) {
                document.getElementById("department").value = data.profile.department || "";
                document.getElementById("year").value = data.profile.year || "2";
                document.getElementById("interest").value = data.profile.interest || "";
                document.getElementById("location").value = data.profile.location || "";
                document.getElementById("career").value = data.profile.career || "";
                
                if (Array.isArray(data.profile.skills)) {
                    data.profile.skills.forEach(skill => {
                        const cb = document.querySelector(`input[name="skills"][value="${skill}"]`);
                        if (cb) cb.checked = true;
                    });
                }
            }
            
            // Update profile progress bar
            const percent = data.completion || 0;
            document.getElementById("profilePercent").textContent = `${percent}%`;
            document.getElementById("profileProgressBar").style.width = `${percent}%`;
            
            // Fetch matched engine opportunities
            fetchMatchedOpportunities();
        }
    } catch (err) {
        console.error("Profile load error:", err);
    }
}

async function fetchMatchedOpportunities() {
    const container = document.getElementById("engineResults");
    container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Calculating AI rankings, skill gaps, and trust verification scores...</p></div>`;
    
    try {
        const res = await fetch("/api/match", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentProfile || {})
        });
        
        if (res.status === 409) {
            container.innerHTML = `<div class="empty-state"><h3>Complete Profile First</h3><p>Fill out your profile details in the Profile tab to enable AI matching.</p></div>`;
            return;
        }
        
        const opportunities = await res.json();
        currentMatchedOpportunities = opportunities;
        renderOpportunityGrid(opportunities, container);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><p>Error loading recommendations: ${err.message}</p></div>`;
    }
}

function renderOpportunityGrid(items, container) {
    if (!Array.isArray(items) || items.length === 0) {
        container.innerHTML = `<div class="empty-state"><h3>No opportunities found</h3><p>Try adjusting your category filters or search query.</p></div>`;
        return;
    }

    let filtered = items.filter(opp => {
        const matchesCategory = activeCategoryFilter === "All" || opp.category.toLowerCase() === activeCategoryFilter.toLowerCase();
        const searchText = (opp.title + " " + opp.organization + " " + opp.skills + " " + opp.description).toLowerCase();
        const matchesSearch = !currentSearchTerm || searchText.includes(currentSearchTerm.toLowerCase());
        return matchesCategory && matchesSearch;
    });

    if (currentSortOrder === "match") {
        filtered.sort((a, b) => (b.match_score || 0) - (a.match_score || 0));
    } else {
        filtered.sort((a, b) => (a.deadline || "9999-12-31").localeCompare(b.deadline || "9999-12-31"));
    }

    if (filtered.length === 0) {
        container.innerHTML = `<div class="empty-state"><h3>No matching results</h3><p>No opportunities fit the selected criteria.</p></div>`;
        return;
    }

    container.innerHTML = filtered.map(opp => {
        const trust = opp.trust_info || { trust_badge: "Verified", trust_score: 100, reason: "Verified Official Source" };
        const trustClass = trust.trust_badge.toLowerCase().replace(" ", "-");
        
        const matchingSkillsTags = (opp.skill_gap?.matching_skills || []).map(s => `<span class="skill-tag match">✓ ${s}</span>`).join("");
        const missingSkillsTags = (opp.skill_gap?.missing_skills || []).map(s => `<span class="skill-tag missing">⚠ ${s}</span>`).join("");
        
        const courseRecs = (opp.skill_gap?.recommended_courses || []).map(c => `
            <a class="course-rec-link" href="${c.url}" target="_blank">🎓 Course Pick: ${c.title} (${c.organization})</a>
        `).join("");

        const actionPlanSteps = (opp.action_plan || []).map(step => `
            <div class="plan-step"><strong>${step.week}: ${step.title}</strong> — ${step.action}</div>
        `).join("");

        return `
            <article class="opp-card">
                <div class="card-header-bar">
                    <span class="badge-category">${opp.category}</span>
                    <span class="badge-trust ${trustClass}">🛡️ ${trust.trust_badge} (${trust.trust_score}%)</span>
                    ${opp.match_score ? `<span class="badge-match-score">⚡ ${opp.match_score}% Match</span>` : ''}
                </div>

                <div>
                    <h3 class="opp-title">${opp.title}</h3>
                    <div class="opp-org">🏢 ${opp.organization} • 📍 ${opp.location || 'Remote'} • 📅 Deadline: ${opp.deadline || 'Upcoming'}</div>
                </div>

                <p class="opp-desc">${opp.description || ''}</p>

                ${opp.why_match ? `
                    <div class="why-match-box">
                        <div class="why-match-title">💡 Why This Match?</div>
                        <div>${opp.why_match}</div>
                    </div>
                ` : ''}

                <div class="skill-gap-box">
                    <div style="font-weight: 700; margin-bottom: 6px; font-size: 0.8rem; color: var(--text-muted);">🎯 Skill Gap Analysis:</div>
                    <div>${matchingSkillsTags} ${missingSkillsTags || '<span style="color: var(--accent-emerald);">All required skills matched!</span>'}</div>
                    ${courseRecs ? `<div style="margin-top: 8px;">${courseRecs}</div>` : ''}
                </div>

                <div class="action-plan-container">
                    <button type="button" class="action-plan-toggle" onclick="toggleActionPlan(${opp.id})">
                        <span>📅 View 30-Day Action Plan</span> <span>▼</span>
                    </button>
                    <div id="actionPlanSteps-${opp.id}" class="action-plan-steps">
                        ${actionPlanSteps}
                    </div>
                </div>

                <div class="card-actions">
                    <button class="btn-action-icon" title="Save Opportunity" onclick="updateApplicationStatus(${opp.id}, 'saved')">📌 Save</button>
                    <button class="btn-action-icon" title="Mark Applied" onclick="updateApplicationStatus(${opp.id}, 'applied')">🚀 Applied</button>
                    <a class="btn-apply" href="${opp.registration_url || opp.link || '#'}" target="_blank" rel="noopener">Official Portal ↗</a>
                </div>
            </article>
        `;
    }).join("");
}

function toggleActionPlan(id) {
    const el = document.getElementById(`actionPlanSteps-${id}`);
    if (el) {
        el.style.display = (el.style.display === "flex") ? "none" : "flex";
    }
}

// TOOLBAR & FILTERS
function initEngineToolbar() {
    const searchInput = document.getElementById("searchInput");
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            currentSearchTerm = e.target.value;
            renderOpportunityGrid(currentMatchedOpportunities, document.getElementById("engineResults"));
        });
    }

    const sortSelect = document.getElementById("sortSelect");
    if (sortSelect) {
        sortSelect.addEventListener("change", (e) => {
            currentSortOrder = e.target.value;
            renderOpportunityGrid(currentMatchedOpportunities, document.getElementById("engineResults"));
        });
    }

    document.querySelectorAll(".cat-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            document.querySelectorAll(".cat-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            activeCategoryFilter = pill.getAttribute("data-category");
            renderOpportunityGrid(currentMatchedOpportunities, document.getElementById("engineResults"));
        });
    });
}

// NATURAL LANGUAGE SEARCH
function initNLPSearch() {
    const form = document.getElementById("nlpForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const query = document.getElementById("nlpQuery").value.trim();
        if (!query) return;

        const resultsContainer = document.getElementById("nlpResults");
        resultsContainer.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Parsing natural language query and mapping profile intent...</p></div>`;

        try {
            const res = await fetch("/api/nlp-search", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query })
            });

            const data = await res.json();
            const intentBox = document.getElementById("nlpIntentBox");
            const tagsContainer = document.getElementById("intentTags");
            
            intentBox.style.display = "block";
            tagsContainer.innerHTML = `
                <span class="intent-pill">Category: ${data.intent.detected_category}</span>
                ${data.intent.detected_dept ? `<span class="intent-pill">Dept: ${data.intent.detected_dept}</span>` : ''}
                ${data.intent.detected_year ? `<span class="intent-pill">Year: ${data.intent.detected_year}</span>` : ''}
                ${data.intent.detected_skills.length ? `<span class="intent-pill">Skills: ${data.intent.detected_skills.join(", ")}</span>` : ''}
            `;

            renderOpportunityGrid(data.results, resultsContainer);
        } catch (err) {
            resultsContainer.innerHTML = `<div class="empty-state"><p>Search error: ${err.message}</p></div>`;
        }
    });
}

function fillPrompt(text) {
    const input = document.getElementById("nlpQuery");
    if (input) {
        input.value = text;
        document.getElementById("nlpForm").dispatchEvent(new Event("submit"));
    }
}

// APPLICATION TRACKER
async function loadTrackerMetrics() {
    const trackerContainer = document.getElementById("trackerContainer");
    if (!trackerContainer) return;

    try {
        const res = await fetch("/api/applications");
        if (!res.ok) return;
        
        const data = await res.json();
        document.getElementById("metricSavedCount").textContent = data.metrics.saved || 0;
        document.getElementById("metricAppliedCount").textContent = data.metrics.applied || 0;
        document.getElementById("metricCompletedCount").textContent = data.metrics.completed || 0;

        if (!data.applications || data.applications.length === 0) {
            trackerContainer.innerHTML = `<div class="empty-state"><p>No saved or applied opportunities yet. Bookmark opportunities from the Matched Engine to track them here!</p></div>`;
            return;
        }

        renderOpportunityGrid(data.applications, trackerContainer);
    } catch (err) {
        console.error("Tracker load error:", err);
    }
}

async function updateApplicationStatus(opportunityId, status) {
    try {
        const res = await fetch("/api/applications", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ opportunity_id: opportunityId, status })
        });
        if (res.ok) {
            alert(`Opportunity successfully marked as ${status.toUpperCase()}!`);
            loadTrackerMetrics();
        }
    } catch (err) {
        alert("Failed to update status: " + err.message);
    }
}

// PERSONALIZED LEARNING PATH
function initLearningPath() {
    const goalSelect = document.getElementById("careerGoalSelect");
    if (goalSelect) {
        goalSelect.addEventListener("change", loadLearningPath);
    }
}

async function loadLearningPath() {
    const container = document.getElementById("roadmapNodes");
    if (!container) return;

    const goal = document.getElementById("careerGoalSelect")?.value || "AI Engineer";
    container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Generating personalized learning roadmap...</p></div>`;

    try {
        const res = await fetch(`/api/learning-path?goal=${encodeURIComponent(goal)}`);
        const data = await res.json();

        document.getElementById("roadmapTitle").textContent = data.title;
        container.innerHTML = data.stages.map((stg) => `
            <div class="roadmap-step-card">
                <div class="roadmap-step-dot"></div>
                <div class="roadmap-step-content">
                    <div class="roadmap-step-title">${stg.stage} [${stg.type}]</div>
                    <div style="font-weight: 700; font-size: 1.05rem; margin: 4px 0; color: var(--text-main);">${stg.title || stg.description}</div>
                    ${stg.org ? `<div style="font-size: 0.85rem; color: var(--primary);">Verified Platform: ${stg.org}</div>` : ''}
                </div>
            </div>
        `).join("");
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><p>Error loading learning path.</p></div>`;
    }
}

// PROFILE FORM SUBMIT
function initProfileForm() {
    const form = document.getElementById("profileForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const selectedSkills = [...document.querySelectorAll('input[name="skills"]:checked')].map(cb => cb.value);
        const profile = {
            department: document.getElementById("department").value,
            year: document.getElementById("year").value,
            skills: selectedSkills,
            interest: document.getElementById("interest").value,
            interests: [document.getElementById("interest").value],
            location: document.getElementById("location").value,
            career: document.getElementById("career").value
        };

        try {
            const res = await fetch("/api/profile", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(profile)
            });

            if (res.ok) {
                alert("Profile updated! Refreshing Decision Engine matches...");
                currentProfile = profile;
                loadProfileAndMatches();
                document.querySelector('.nav-tab[data-target="section-engine"]').click();
            }
        } catch (err) {
            alert("Failed to save profile: " + err.message);
        }
    });
}