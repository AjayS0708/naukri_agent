import type { ProfileResponse } from "../types/api";
import { PageHeader } from "../ui/PageHeader";
import { ProfileWorkspace } from "../components/ProfileWorkspace";

interface ProfilePageProps {
  onProfileChange: (profile: ProfileResponse) => void;
}

export function ProfilePage({ onProfileChange }: ProfilePageProps) {
  return (
    <div className="page">
      <PageHeader
        eyebrow="Account"
        title="Profile"
        description="Resume upload, extraction review, and confirmation. The confirmed profile drives every application the agent submits."
      />
      <ProfileWorkspace onProfileChange={onProfileChange} />
    </div>
  );
}
