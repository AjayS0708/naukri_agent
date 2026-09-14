import { useEffect, useState } from "react";
import { Check, FileUp, LoaderCircle, Save } from "lucide-react";
import { confirmProfile, getProfile, updateProfile, uploadResume } from "../services/api";
import type { ProfileData, ProfileResponse } from "../types/api";

const emptyProfile: ProfileData = { education: [], skills: [], programming_languages: [], frameworks: [], tools: [], projects: [], certifications: [], experience: [] };
const split = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

export function ProfileWorkspace({ onProfileChange }: { onProfileChange: (profile: ProfileResponse) => void }) {
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [data, setData] = useState<ProfileData>(emptyProfile);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { getProfile().then((current) => { setProfile(current); setData(current.data ?? emptyProfile); }).catch(() => setMessage("Profile service is unavailable.")); }, []);
  const apply = (next: ProfileResponse) => { setProfile(next); setData(next.data ?? emptyProfile); onProfileChange(next); };
  const upload = async (file?: File) => { if (!file) return; setBusy(true); setMessage(null); try { await uploadResume(file); apply(await getProfile()); setMessage("Resume extracted. Review the profile before confirmation."); } catch (error) { setMessage(error instanceof Error ? error.message : "Upload failed."); } finally { setBusy(false); } };
  const save = async () => { setBusy(true); setMessage(null); try { apply(await updateProfile(data)); setMessage("Profile edits saved. Confirmation is still required."); } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save profile."); } finally { setBusy(false); } };
  const confirm = async () => { setBusy(true); setMessage(null); try { apply(await confirmProfile()); setMessage("Profile confirmed."); } catch (error) { setMessage(error instanceof Error ? error.message : "Could not confirm profile."); } finally { setBusy(false); } };
  const set = <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => setData((current) => ({ ...current, [key]: value }));
  const status = profile?.status ?? "EMPTY";
  return <section className="profile-workspace"><div className="section-heading"><div><p className="eyebrow">PROFILE SETUP</p><h2>Resume and profile</h2><p>{profile?.original_filename ?? "No resume uploaded"}</p></div><span className="profile-status">{status.replaceAll("_", " ")}</span></div>
    <label className="upload-zone"><FileUp size={22} /><span><b>Upload PDF resume</b><small>PDF only, up to 10 MB. The text is used only for profile extraction.</small></span><input type="file" accept="application/pdf,.pdf" onChange={(event) => upload(event.target.files?.[0])} disabled={busy} /></label>
    {profile?.data && <div className="profile-form"><div className="form-grid"><Field label="Name" value={data.name ?? ""} onChange={(value) => set("name", value || null)} /><Field label="Current role" value={data.current_role ?? ""} onChange={(value) => set("current_role", value || null)} /><Field label="Location" value={data.location ?? ""} onChange={(value) => set("location", value || null)} /><Field label="Notice period" value={data.notice_period ?? ""} onChange={(value) => set("notice_period", value || null)} /></div><div className="form-grid"><Field label="Skills" value={data.skills.join(", ")} onChange={(value) => set("skills", split(value))} /><Field label="Programming languages" value={data.programming_languages.join(", ")} onChange={(value) => set("programming_languages", split(value))} /><Field label="Frameworks" value={data.frameworks.join(", ")} onChange={(value) => set("frameworks", split(value))} /><Field label="Tools" value={data.tools.join(", ")} onChange={(value) => set("tools", split(value))} /></div><div className="profile-actions"><button className="button secondary" type="button" onClick={save} disabled={busy}><Save size={16} />Save edits</button><button className="button" type="button" onClick={confirm} disabled={busy || status !== "REVIEW_REQUIRED"}><Check size={16} />Confirm profile</button></div></div>}
    {busy && <p className="inline-state"><LoaderCircle size={16} />Working with your profile...</p>}{message && <p className="inline-message">{message}</p>}
  </section>;
}
function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="field"><span>{label}</span><input value={value} onChange={(event) => onChange(event.target.value)} /></label>; }
