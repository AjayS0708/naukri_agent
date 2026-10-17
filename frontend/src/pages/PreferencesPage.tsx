import { PageHeader } from "../ui/PageHeader";
import { JobPreferences } from "../components/JobPreferences";

export function PreferencesPage() {
  return (
    <div className="page">
      <PageHeader
        eyebrow="Settings"
        title="Preferences"
        description="Locations, role scope, employment types, application strategy, and the ₹3 LPA minimum disclosed salary. Saved values are never reset automatically."
      />
      <JobPreferences />
    </div>
  );
}
