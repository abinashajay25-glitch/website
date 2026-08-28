let currentProfile = null;
let currentMatchedOpportunities = [];
let activeCategoryFilter = "All";

document.addEventListener("DOMContentLoaded", () => {
    initNavigationTabs();
    initProfileForm();
    initCategoryPills();
    initResumeMatcher();
    initAIChat();
    loadProfileAndMatches();
    loadAdminMetrics();
});

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
            
            if (targetId === "section-30days") loadNext30Days(30);
            if (targetId === "section-tracker") loadTrackerMetrics();
            if (targetId === "section-roadmap") loadCareerRoadmap();
            if (targetId === "section-admin") loadAdminMetrics();
        });
    });
}

function initCategoryPills() {
    document.querySelectorAll(".cat-pill").forEach(pill => {
        pill.addEventListener("click", () => {
            document.querySelectorAll(".cat-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");
            activeCategoryFilter = pill.getAttribute("data-category");
            renderOpportunityGrid(currentMatchedOpportunities, document.getElementById("engineResults"));
        });
    });
}

async function loadProfileAndMatches() {
    try {
        const res = await fetch("/api/profile");
        if (res.status === 401) {
            window.location.href = "/login";
            return;
        }
        const data = await res.json();
        if (data.authenticated) {
            currentProfile = data.profile || {};
            if (data.profile) {
                document.getElementById("department").value = data.profile.department || "";
                document.getElementById("year").value = data.profile.year || "2";
                document.getElementById("location").value = data.profile.location || "";
                document.getElementById("career").value = data.profile.career || "AI Engineer";
                if (Array.isArray(data.profile.skills)) {
                    data.profile.skills.forEach(skill => {
                        const cb = document.querySelector(`input[name="skills"][value="${skill}"]`);
                        if (cb) cb.checked = true;
                    });
                }
            }
            fetchMatchedOpportunities();
        }
    } catch (err) {
        console.error("Profile load error:", err);
    }
}

async function fetchMatchedOpportunities() {
    const container = document.getElementById("engineResults");
    container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Calculating eligibility checks and AI match rankings...</p></div>`;
    
    try {
        const res = await fetch("/api/match", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentProfile || {})
        });
        const opportunities = await res.json();
        currentMatchedOpportunities = opportunities;
        renderOpportunityGrid(opportunities, container);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><p>Error loading recommendations: ${err.message}</p></div>`;
    }
}

function renderOpportunityGrid(items, container) {
    if (!Array.isArray(items) || items.length === 0) {
        container.innerHTML = `<div class="empty-state"><h3>No matching opportunities found</h3><p>Try adjusting your category filters or search query.</p></div>`;
        return;
    }

    let filtered = items.filter(opp => {
        return activeCategoryFilter === "All" || opp.category.toLowerCase() === activeCategoryFilter.toLowerCase();
    });

    if (filtered.length === 0) {
        container.innerHTML = `<div class="empty-state"><h3>No opportunities in category "${activeCategoryFilter}"</h3></div>`;
        return;
    }

    container.innerHTML = filtered.map(opp => {
        const trust = opp.trust_info || { trust_badge: "✓ Official Source Verified", trust_score: 100 };
        const trustClass = trust.trust_score >= 85 ? "verified" : "unverified";
        const elig = opp.eligibility_eval || { status: "🟢 Eligible", reasons: [] };
        
        const whyChecklist = (opp.why_match_checklist || []).map(item => `
            <div class="checklist-item">${item}</div>
        `).join("");

        const eligReasons = (elig.reasons || []).map(r => `<div>${r}</div>`).join("");

        return `
            <article class="opp-card">
                <div class="card-header-bar">
                    <span class="badge-category">${opp.category}</span>
                    <span class="badge-trust ${trustClass}">${trust.trust_badge}</span>
                    <span class="badge-match-score">⚡ ${opp.match_score || 85}% Match</span>
                </div>

                <div>
                    <h3 class="opp-title">${opp.title}</h3>
                    <div class="opp-org">🏢 ${opp.organization} • 📍 ${opp.location || 'Remote'} • ${opp.deadline_badge || 'Upcoming'}</div>
                </div>

                <p class="opp-desc">${opp.description || ''}</p>

                <div class="eligibility-box">
                    <div class="eligibility-status">Eligibility: ${elig.status}</div>
                    <div style="font-size: 0.78rem; color: var(--text-muted);">${eligReasons}</div>
                </div>

                ${whyChecklist ? `
                    <div class="why-match-box">
                        <div class="why-match-title">💡 Why this matches you:</div>
                        ${whyChecklist}
                    </div>
                ` : ''}

                <div class="card-actions">
                    <button class="btn-action-icon" onclick="updateAppStatus(${opp.id}, 'Saved')">📌 Save</button>
                    <button class="btn-action-icon" onclick="updateAppStatus(${opp.id}, 'Applied')">🚀 Apply</button>
                    <a class="btn-apply" href="${opp.registration_url || opp.link || '#'}" target="_blank" rel="noopener">Official Source Portal ↗</a>
                </div>
            </article>
        `;
    }).join("");
}

// NEXT 30 DAYS
async function loadNext30Days(days) {
    const container = document.getElementById("next30DaysResults");
    container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Fetching opportunities closing in the next ${days} days...</p></div>`;
    
    try {
        const res = await fetch(`/api/opportunities/next-30-days?days=${days}`);
        const data = await res.json();
        renderOpportunityGrid(data.opportunities, container);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><p>Error loading closing opportunities.</p></div>`;
    }
}

// ADVANCED SEARCH
async function triggerAdvancedSearch() {
    const query = document.getElementById("searchInputField").value.trim();
    const container = document.getElementById("searchResults");
    container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Searching database...</p></div>`;

    try {
        const res = await fetch(`/api/opportunities?search=${encodeURIComponent(query)}`);
        const opportunities = await res.json();
        renderOpportunityGrid(opportunities, container);
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><p>Search failed.</p></div>`;
    }
}

// APPLICATION TRACKER
async function loadTrackerMetrics() {
    const trackerContainer = document.getElementById("trackerContainer");
    try {
        const res = await fetch("/api/applications");
        if (!res.ok) return;
        const data = await res.json();

        document.getElementById("metricSaved").textContent = data.metrics.Saved || 0;
        document.getElementById("metricPlanning").textContent = data.metrics["Planning to Apply"] || 0;
        document.getElementById("metricApplied").textContent = data.metrics.Applied || 0;
        document.getElementById("metricInterview").textContent = data.metrics.Interview || 0;
        document.getElementById("metricSelected").textContent = data.metrics.Selected || 0;

        renderOpportunityGrid(data.applications, trackerContainer);
    } catch (err) {
        console.error("Tracker error:", err);
    }
}

async function updateAppStatus(opportunityId, status) {
    try {
        const res = await fetch("/api/applications", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ opportunity_id: opportunityId, status })
        });
        if (res.ok) {
            alert(`Application status updated to "${status}"!`);
            loadTrackerMetrics();
        }
    } catch (err) {
        alert("Failed to update status: " + err.message);
    }
}

// RESUME MATCHER
function initResumeMatcher() {
    const form = document.getElementById("resumeForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const resumeText = document.getElementById("resumeText").value.trim();
        const container = document.getElementById("resumeResults");
        container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Parsing resume skills and matching database opportunities...</p></div>`;

        try {
            const res = await fetch("/api/resume-match", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ resume_text: resumeText })
            });
            const data = await res.json();
            
            const box = document.getElementById("resumeAnalysisBox");
            const tags = document.getElementById("resumeSkillsTags");
            box.style.display = "block";
            tags.innerHTML = data.extracted_skills.map(s => `<span class="intent-pill">Skill: ${s}</span>`).join(" ");

            renderOpportunityGrid(data.opportunities, container);
        } catch (err) {
            container.innerHTML = `<div class="empty-state"><p>Resume parsing failed.</p></div>`;
        }
    });
}

// AI CAREER ROADMAP
async function loadCareerRoadmap() {
    const container = document.getElementById("roadmapNodes");
    const goal = document.getElementById("careerGoalSelect")?.value || "AI Engineer";
    container.innerHTML = `<div class="loading-state"><div class="spinner"></div><p>Generating AI career progression roadmap...</p></div>`;

    try {
        const res = await fetch(`/api/career-roadmap?goal=${encodeURIComponent(goal)}`);
        const data = await res.json();

        document.getElementById("roadmapTitle").textContent = `${data.goal} Progression Path`;
        container.innerHTML = data.nodes.map(n => `
            <div class="roadmap-step-card">
                <div style="font-weight: 800; color: var(--accent-cyan); font-size: 0.85rem;">${n.step}</div>
                <div style="font-size: 1.05rem; font-weight: 700; margin-top: 4px; color: var(--text-main);">${n.details}</div>
            </div>
        `).join("");
    } catch (err) {
        container.innerHTML = `<div class="empty-state"><p>Failed to load roadmap.</p></div>`;
    }
}

function formatMarkdown(text) {
    if (!text) return "";
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, '<code style="background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-family: monospace;">$1</code>')
        .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" rel="noopener" style="color: var(--accent-cyan); font-weight: bold; text-decoration: underline;">$1 ↗</a>')
        .replace(/\n/g, '<br>');
}

// AI CHAT ASSISTANT
function initAIChat() {
    const form = document.getElementById("chatForm");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const input = document.getElementById("chatInput");
        const msg = input.value.trim();
        if (!msg) return;

        const history = document.getElementById("chatHistory");
        history.innerHTML += `<div class="chat-msg user">${msg}</div>`;
        input.value = "";
        history.scrollTop = history.scrollHeight;

        try {
            const res = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: msg })
            });

            let data = {};
            const contentType = res.headers.get("content-type") || "";
            if (contentType.includes("application/json")) {
                data = await res.json();
            } else {
                data = { reply: "Sorry, received unexpected response from AI Assistant server." };
            }

            const formattedReply = formatMarkdown(data.reply || "No response generated.");
            history.innerHTML += `<div class="chat-msg bot">${formattedReply}</div>`;
            history.scrollTop = history.scrollHeight;
        } catch (err) {
            history.innerHTML += `<div class="chat-msg bot">Sorry, error reaching NextStep AI Assistant. ${err.message}</div>`;
            history.scrollTop = history.scrollHeight;
        }
    });
}

// ADMIN METRICS
async function loadAdminMetrics() {
    try {
        const res = await fetch("/api/admin/metrics");
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById("adminTotalOpps").textContent = data.total_opportunities;
        document.getElementById("adminVerifiedOpps").textContent = data.verified_opportunities;
        document.getElementById("adminTotalUsers").textContent = data.total_users;
    } catch (err) {
        console.error("Admin load error:", err);
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
                alert("Profile saved! Recalculating AI match recommendations...");
                currentProfile = profile;
                fetchMatchedOpportunities();
                document.querySelector('.nav-tab[data-target="section-engine"]').click();
            }
        } catch (err) {
            alert("Failed to save profile.");
        }
    });
}