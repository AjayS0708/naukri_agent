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
            setMessage("Could not load preferences.");
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
                    <h2>Job Preferences & Matching Engine</h2>
                    <p>Define strict limits and scopes for AI evaluation.</p>
                </div>
                <span className="profile-status"><Settings2 size={16} /> Configured</span>
            </div>

            <div className="profile-form mt-4">
                <div className="profile-section">
                    <h3>Target Configuration</h3>
                    <div className="form-grid">
                        <label className="field">
                            <span>Job Titles / Scope (comma separated)</span>
                            <input
                                value={data.job_titles}
                                onChange={(e) => setData({ ...data, job_titles: e.target.value })}
                                placeholder="e.g. Data Analyst, Business Analyst"
                            />
                        </label>
                        <label className="field">
                            <span>Locations (comma separated)</span>
                            <input
                                value={data.locations}
                                onChange={(e) => setData({ ...data, locations: e.target.value })}
                                placeholder="e.g. Bengaluru, Remote"
                            />
                        </label>
                        <label className="field">
                            <span>Minimum Salary (LPA)</span>
                            <input
                                type="number"
                                value={data.min_salary_lpa}
                                onChange={(e) => setData({ ...data, min_salary_lpa: e.target.value })}
                                placeholder="e.g. 4"
                            />
                        </label>
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
                    <h3>Application Aggressiveness</h3>
                    <div className="field" style={{ maxWidth: '300px' }}>
                        <select
                            value={data.aggressiveness}
                            onChange={(e) => setData({ ...data, aggressiveness: e.target.value })}
                            className="w-full border border-[var(--color-border)] p-2 rounded text-[var(--color-text)] bg-white"
                            style={{ padding: '8px 10px', border: '1px solid var(--color-border)', borderRadius: '4px' }}
                        >
                            <option value="CONSERVATIVE">Conservative</option>
                            <option value="BALANCED">Balanced</option>
                            <option value="AGGRESSIVE">Aggressive</option>
                        </select>
                    </div>
                </div>

                <div className="profile-actions">
                    <button className="button" type="button" onClick={savePreferences} disabled={busy}>
                        {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                        Save Automation Settings
                    </button>
                </div>
            </div>

            {message && <p className="inline-message mt-4">{message}</p>}
        </section>
    );
}
