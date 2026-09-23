import { useEffect, useState } from "react";
import { Save, Settings2, LoaderCircle } from "lucide-react";

export function JobPreferences() {
    const [busy, setBusy] = useState(false);
    const [data, setData] = useState({
        locations: "",
        job_titles: "",
        employment_types: "",
        min_salary_lpa: "4",
        aggressiveness: "BALANCED",
    });
    const [message, setMessage] = useState<string | null>(null);

    useEffect(() => {
        fetchPreferences();
    }, []);

    const fetchPreferences = async () => {
        setBusy(true);
        try {
            const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
            const res = await fetch(`${BASE_URL}/api/matching/preferences`);
            if (res.ok) {
                const pref = await res.json();
                setData({
                    locations: (pref.locations || []).join(", "),
                    job_titles: (pref.job_titles || []).join(", "),
                    employment_types: (pref.employment_types || []).join(", "),
                    min_salary_lpa: pref.min_salary_lpa?.toString() || "",
                    aggressiveness: pref.aggressiveness || "BALANCED",
                });
            }
        } catch {
            setMessage("Preferences are temporarily unavailable. Please try again.");
        } finally {
            setBusy(false);
        }
    };

    const savePreferences = async () => {
        setBusy(true);
        setMessage(null);
        try {
            const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
            const splitStr = (str: string) => str.split(",").map(i => i.trim()).filter(Boolean);

            const payload = {
                locations: splitStr(data.locations),
                job_titles: splitStr(data.job_titles),
                employment_types: splitStr(data.employment_types),
                min_salary_lpa: data.min_salary_lpa ? parseFloat(data.min_salary_lpa) : null,
                aggressiveness: data.aggressiveness,
                max_daily_applications: 20,
                max_hourly_applications: 4,
            };

            const res = await fetch(`${BASE_URL}/api/matching/preferences`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            if (!res.ok) throw new Error("Failed to save.");
            setMessage("Preferences saved successfully.");
        } catch (err: any) {
            setMessage(err.message || "Failed to save preferences.");
        } finally {
            setBusy(false);
        }
    };

    return (
        <section className="profile-workspace">
            <div className="section-heading">
                <div>
                    <p className="eyebrow">AUTOMATION SETTINGS</p>
                    <h2>Job Preferences</h2>
                    <p className="text-sm text-[var(--color-text-secondary)]">Configure job search criteria and automation behavior</p>
                </div>
                <span className="profile-status"><Settings2 size={16} /> Configured</span>
            </div>

            <div className="profile-form">
                <div className="profile-section">
                    <h3>TARGET ROLES</h3>
                    <p className="section-description">Job titles and search terms the agent will look for</p>
                    <div className="form-grid">
                        <label className="field">
                            <span>Job Titles / Scope (comma separated)</span>
                            <input
                                value={data.job_titles}
                                onChange={(e) => setData({ ...data, job_titles: e.target.value })}
                                placeholder="e.g. Data Analyst, Business Analyst"
                            />
                        </label>
                    </div>
                </div>

                <div className="profile-section">
                    <h3>LOCATIONS</h3>
                    <p className="section-description">Preferred work locations for job search</p>
                    <div className="form-grid">
                        <label className="field">
                            <span>Locations (comma separated)</span>
                            <input
                                value={data.locations}
                                onChange={(e) => setData({ ...data, locations: e.target.value })}
                                placeholder="e.g. Bengaluru, Remote"
                            />
                        </label>
                    </div>
                </div>

                <div className="profile-section">
                    <h3>COMPENSATION</h3>
                    <p className="section-description">Only jobs with a disclosed salary below this threshold will be excluded</p>
                    <div className="form-grid">
                        <label className="field">
                            <span>Minimum Salary (LPA)</span>
                            <input
                                type="number"
                                value={data.min_salary_lpa}
                                onChange={(e) => setData({ ...data, min_salary_lpa: e.target.value })}
                                placeholder="e.g. 4"
                            />
                        </label>
                    </div>
                </div>

                <div className="profile-section">
                    <h3>EMPLOYMENT TYPE</h3>
                    <p className="section-description">Types of employment arrangements to consider</p>
                    <div className="form-grid">
                        <label className="field">
                            <span>Employment Types (comma separated)</span>
                            <input
                                value={data.employment_types}
                                onChange={(e) => setData({ ...data, employment_types: e.target.value })}
                                placeholder="e.g. Full-time, Internship"
                            />
                        </label>
                    </div>
                </div>

                <div className="profile-section">
                    <h3>APPLICATION STRATEGY</h3>
                    <p className="section-description">How aggressively the agent should apply to matching jobs</p>
                    <div className="field">
                        <select
                            value={data.aggressiveness}
                            onChange={(e) => setData({ ...data, aggressiveness: e.target.value })}
                        >
                            <option value="CONSERVATIVE">Conservative - Only high-confidence matches</option>
                            <option value="BALANCED">Balanced - Good matches with moderate confidence</option>
                            <option value="AGGRESSIVE">Aggressive - Broad matching including lower confidence</option>
                        </select>
                    </div>
                </div>

                <div className="profile-actions">
                    <button className="button" type="button" onClick={savePreferences} disabled={busy}>
                        {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                        Save Preferences
                    </button>
                </div>
            </div>

            {message && <p className="inline-message">{message}</p>}
        </section>
    );
}
