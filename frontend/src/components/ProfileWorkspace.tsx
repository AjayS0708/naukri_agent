import { useEffect, useState } from "react";
import { Check, FileUp, LoaderCircle, Save } from "lucide-react";
import { confirmProfile, getProfile, updateProfile, uploadResume } from "../services/api";
import type { Education, Experience, ProfileData, ProfileResponse, Project } from "../types/api";

const emptyProfile: ProfileData = {
  education: [],
  skills: [],
  programming_languages: [],
  frameworks: [],
  tools: [],
  projects: [],
  certifications: [],
  experience: [],
};

const splitCommaSeparated = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

function stringifyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function parseStructuredList<T>(value: string): T[] {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (!Array.isArray(parsed)) {
    throw new Error("Expected a JSON array.");
  }
  return parsed as T[];
}

export function ProfileWorkspace({ onProfileChange }: { onProfileChange: (profile: ProfileResponse) => void }) {
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [data, setData] = useState<ProfileData>(emptyProfile);
  const [educationJson, setEducationJson] = useState("[]");
  const [experienceJson, setExperienceJson] = useState("[]");
  const [projectsJson, setProjectsJson] = useState("[]");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [extractionState, setExtractionState] = useState<string | null>(null);

  const syncStructuredEditors = (nextData: ProfileData) => {
    setEducationJson(stringifyJson(nextData.education));
    setExperienceJson(stringifyJson(nextData.experience));
    setProjectsJson(stringifyJson(nextData.projects));
  };

  useEffect(() => {
    getProfile()
      .then((current) => {
        const nextData = current.data ?? emptyProfile;
        setProfile(current);
        setData(nextData);
        syncStructuredEditors(nextData);
      })
      .catch(() => setMessage("Profile service is unavailable."));
  }, []);

  const apply = (next: ProfileResponse) => {
    const nextData = next.data ?? emptyProfile;
    setProfile(next);
    setData(nextData);
    syncStructuredEditors(nextData);
    onProfileChange(next);
  };

  const upload = async (file?: File) => {
    if (!file) {
      return;
    }
    setUploading(true);
    setBusy(true);
    setMessage(null);
    setExtractionState("Uploading resume...");
    try {
      await uploadResume(file);
      setExtractionState("Extracting and validating profile...");
      apply(await getProfile());
      setMessage("Resume extracted. Review and confirm before automation.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploading(false);
      setBusy(false);
      setExtractionState(null);
    }
  };

  const set = <K extends keyof ProfileData>(key: K, value: ProfileData[K]) => {
    setData((current) => ({ ...current, [key]: value }));
  };

  const save = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const parsedEducation = parseStructuredList<Education>(educationJson);
      const parsedExperience = parseStructuredList<Experience>(experienceJson);
      const parsedProjects = parseStructuredList<Project>(projectsJson);
      const nextData: ProfileData = {
        ...data,
        education: parsedEducation,
        experience: parsedExperience,
        projects: parsedProjects,
      };
      apply(await updateProfile(nextData));
      setMessage("Profile edits saved. Confirmation is still required.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save profile.");
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setMessage(null);
    try {
      apply(await confirmProfile());
      setMessage("Profile confirmed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not confirm profile.");
    } finally {
      setBusy(false);
    }
  };

  const status = profile?.status ?? "EMPTY";
  const formattedStatus = status.replaceAll("_", " ");

  return (
    <section className="profile-workspace">
      <div className="section-heading">
        <div>
          <p className="eyebrow">PROFILE SETUP</p>
          <h2>Resume and profile</h2>
          <p>{profile?.original_filename ?? "No resume uploaded"}</p>
        </div>
        <span className="profile-status">{formattedStatus}</span>
      </div>
      <label className="upload-zone">
        <FileUp size={22} />
        <span>
          <b>Upload PDF resume</b>
          <small>PDF only, up to 10 MB. Resume text is used only for profile extraction.</small>
        </span>
        <input type="file" accept="application/pdf,.pdf" onChange={(event) => upload(event.target.files?.[0])} disabled={busy} />
      </label>
      {profile?.data && (
        <div className="profile-form">
          <div className="profile-section">
            <h3>Personal Information</h3>
            <div className="form-grid">
              <Field label="Name" value={data.name ?? ""} onChange={(value) => set("name", value || null)} />
              <Field label="Current role" value={data.current_role ?? ""} onChange={(value) => set("current_role", value || null)} />
              <Field label="Location" value={data.location ?? ""} onChange={(value) => set("location", value || null)} />
              <Field label="Current CTC" value={data.current_ctc ?? ""} onChange={(value) => set("current_ctc", value || null)} />
              <Field label="Notice period" value={data.notice_period ?? ""} onChange={(value) => set("notice_period", value || null)} />
            </div>
          </div>
          <div className="profile-section">
            <h3>Skills</h3>
            <div className="form-grid">
              <Field label="Skills" value={data.skills.join(", ")} onChange={(value) => set("skills", splitCommaSeparated(value))} />
              <Field label="Programming languages" value={data.programming_languages.join(", ")} onChange={(value) => set("programming_languages", splitCommaSeparated(value))} />
              <Field label="Frameworks" value={data.frameworks.join(", ")} onChange={(value) => set("frameworks", splitCommaSeparated(value))} />
              <Field label="Tools" value={data.tools.join(", ")} onChange={(value) => set("tools", splitCommaSeparated(value))} />
              <Field label="Certifications" value={data.certifications.join(", ")} onChange={(value) => set("certifications", splitCommaSeparated(value))} />
            </div>
          </div>
          <JsonSection label="Education" value={educationJson} onChange={setEducationJson} />
          <JsonSection label="Experience" value={experienceJson} onChange={setExperienceJson} />
          <JsonSection label="Projects" value={projectsJson} onChange={setProjectsJson} />
          <div className="profile-actions">
            <button className="button secondary" type="button" onClick={save} disabled={busy}>
              <Save size={16} />
              Save edits
            </button>
            <button className="button" type="button" onClick={confirm} disabled={busy || status !== "REVIEW_REQUIRED"}>
              <Check size={16} />
              Confirm profile
            </button>
          </div>
        </div>
      )}
      {(busy || uploading) && (
        <p className="inline-state">
          <LoaderCircle size={16} />
          {extractionState ?? "Working with your profile..."}
        </p>
      )}
      {message && <p className="inline-message">{message}</p>}
    </section>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function JsonSection({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <div className="profile-section">
      <h3>{label}</h3>
      <label className="field">
        <span>{label} JSON array</span>
        <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={8} />
      </label>
    </div>
  );
}
