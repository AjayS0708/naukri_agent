import { useCallback, useEffect, useState } from "react";
import {
  getAnalyticsApplicationsByDay,
  getAnalyticsDecisionBreakdown,
  getAnalyticsSkipReasons,
  getAnalyticsSummary,
} from "../services/api";
import type { AnalyticsSummary, DayCount, DecisionBreakdown, SkipReasonItem } from "../types/api";
import { EmptyState, ErrorState, LoadingState } from "../components/StateBlocks";
import { PageHeader } from "../ui/PageHeader";
import { StatCard } from "../ui/StatCard";
import {
  AlertTriangle,
  ArrowRightLeft,
  BarChart3,
  CheckCircle2,
  Clock3,
  Compass,
  ExternalLink,
  Sparkles,
  XCircle,
} from "lucide-react";

const PERIODS = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
];

const DECISION_LABELS: Record<string, string> = {
  HIGH_PRIORITY: "High priority",
  NORMAL_PRIORITY: "Normal priority",
  LOW_PRIORITY: "Low priority",
  SKIP: "Skipped",
  HARD_REJECT: "Hard reject",
  NEEDS_ATTENTION: "Needs attention",
};

export function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [breakdown, setBreakdown] = useState<DecisionBreakdown | null>(null);
  const [skipReasons, setSkipReasons] = useState<SkipReasonItem[]>([]);
  const [byDay, setByDay] = useState<DayCount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, breakdownData, skipData, dayData] = await Promise.all([
        getAnalyticsSummary(days),
        getAnalyticsDecisionBreakdown(days),
        getAnalyticsSkipReasons(days, 8),
        getAnalyticsApplicationsByDay(days),
      ]);
      setSummary(summaryData);
      setBreakdown(breakdownData);
      setSkipReasons(skipData);
      setByDay(dayData);
    } catch (err: unknown) {
      setError((err as { message?: string } | null)?.message ?? "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  const maxDay = Math.max(1, ...byDay.map((d) => d.count));

  return (
    <div className="page">
      <PageHeader
        eyebrow="Analytics"
        title="Performance"
        description="Real backend statistics — attempts, outcomes, skip reasons, and trends. Nothing here is estimated."
        actions={
          <div className="segmented" role="tablist" aria-label="Analytics period">
            {PERIODS.map((period) => (
              <button
                key={period.days}
                type="button"
                role="tab"
                aria-selected={days === period.days}
                className={days === period.days ? "active" : ""}
                onClick={() => setDays(period.days)}
              >
                {period.label}
              </button>
            ))}
          </div>
        }
      />

      {loading ? (
        <LoadingState title="Loading analytics…" />
      ) : error ? (
        <ErrorState title="Analytics unavailable" message={error} action={{ label: "Retry", onClick: () => void load() }} />
      ) : summary ? (
        <>
          <div className="stat-grid">
            <StatCard icon={Compass} label="Jobs discovered" value={summary.discovered_jobs} sub={`last ${summary.period_days} days`} />
            <StatCard
              icon={ArrowRightLeft}
              label="Application attempts"
              value={summary.total_applications}
              sub="all recorded rows"
              tone="gray"
            />
            <StatCard
              icon={CheckCircle2}
              label="Applied / submitted"
              value={summary.successful_applications}
              sub={`backend rate ${summary.success_rate}% of attempts`}
              tone="green"
            />
            <StatCard icon={XCircle} label="Skipped" value={summary.skipped_applications} tone="gray" />
            <StatCard
              icon={AlertTriangle}
              label="Needs attention"
              value={summary.needs_attention}
              tone="amber"
              sub="recorded rows · Overview shows unresolved"
            />
            <StatCard icon={ExternalLink} label="External applications" value={summary.external_applications} tone="violet" />
            <StatCard icon={Sparkles} label="AI analyses" value={summary.ai_analyses} sub={`${summary.ai_requests} provider requests`} />
            <StatCard icon={Clock3} label="Discovery runs" value={summary.discovery_runs} tone="gray" />
          </div>

          <section className="card">
            <div className="card-head">
              <span className="card-head-icon">
                <BarChart3 size={16} />
              </span>
              <div>
                <h2 className="card-title">Application attempts by day</h2>
                <p className="card-subtitle">
                  Attempts recorded per day (last {summary.period_days} days) — includes skipped and
                  needs-attention rows, not only confirmed submissions.
                </p>
              </div>
            </div>
            {byDay.length === 0 ? (
              <EmptyState compact title="No attempts in this period" />
            ) : (
              <div className="bar-chart" role="img" aria-label="Application attempts by day">
                {byDay.map((day) => (
                  <div key={day.date} className="bar-col" title={`${day.date}: ${day.count} attempt(s)`}>
                    <span className="bar-value">{day.count}</span>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ height: `${Math.max(4, (day.count / maxDay) * 100)}%` }} />
                    </div>
                    <span className="bar-label">{day.date.slice(5)}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          <div className="two-col">
            <section className="card">
              <div className="card-head">
                <span className="card-head-icon">
                  <BarChart3 size={16} />
                </span>
                <div>
                  <h2 className="card-title">Matching decisions</h2>
                  <p className="card-subtitle">Deterministic decision outcomes for jobs evaluated in this period.</p>
                </div>
              </div>
              {breakdown && breakdown.total > 0 ? (
                <ul className="breakdown-list">
                  {Object.entries(breakdown.breakdown).map(([key, count]) => {
                    const percentage = breakdown.percentages[key] ?? 0;
                    return (
                      <li key={key} className="breakdown-row">
                        <span className="breakdown-name">{DECISION_LABELS[key] ?? key.replaceAll("_", " ")}</span>
                        <span className="breakdown-track">
                          <span className="breakdown-fill" style={{ width: `${percentage}%` }} />
                        </span>
                        <span className="breakdown-nums">
                          <b>{count}</b> · {percentage.toFixed(1)}%
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState compact title="No decisions recorded in this period" />
              )}
            </section>

            <section className="card">
              <div className="card-head">
                <span className="card-head-icon">
                  <AlertTriangle size={16} />
                </span>
                <div>
                  <h2 className="card-title">Top skip reasons</h2>
                  <p className="card-subtitle">Why jobs were excluded, from recorded application rows.</p>
                </div>
              </div>
              {skipReasons.length > 0 ? (
                <ul className="reason-bars">
                  {skipReasons.map((item) => (
                    <li key={item.reason}>
                      <span className="reason-text" title={item.reason}>
                        {item.reason}
                      </span>
                      <span className="badge tone-gray">{item.count}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState compact title="No skip reasons recorded in this period" />
              )}
            </section>
          </div>

          <p className="result-line">
            Attempts (all rows) and applied/submitted counts are separate metrics — external applications and
            ambiguous submissions are never counted as confirmed successes.
          </p>
        </>
      ) : (
        <EmptyState title="No analytics data" message="Start the agent to begin tracking performance." />
      )}
    </div>
  );
}
