import { useEffect, useState } from "react";
import { BarChart3, TrendingUp, AlertCircle, CheckCircle, XCircle, Clock } from "lucide-react";

interface AnalyticsSummary {
  period_days: number;
  discovered_jobs: number;
  total_applications: number;
  successful_applications: number;
  skipped_applications: number;
  needs_attention: number;
  external_applications: number;
  success_rate: number;
  ai_requests: number;
  ai_analyses: number;
  discovery_runs: number;
}

interface DecisionBreakdown {
  breakdown: {
    HIGH_PRIORITY: number;
    NORMAL_PRIORITY: number;
    LOW_PRIORITY: number;
    SKIP: number;
    HARD_REJECT: number;
    NEEDS_ATTENTION: number;
  };
  total: number;
  percentages: {
    [key: string]: number;
  };
}

interface SkipReason {
  reason: string;
  count: number;
}

export function AnalyticsDashboard() {
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [decisionBreakdown, setDecisionBreakdown] = useState<DecisionBreakdown | null>(null);
  const [skipReasons, setSkipReasons] = useState<SkipReason[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        setLoading(true);
        const [analyticsRes, breakdownRes, skipRes] = await Promise.all([
          fetch("http://127.0.0.1:8000/api/analytics/summary?days=30"),
          fetch("http://127.0.0.1:8000/api/analytics/decision-breakdown?days=30"),
          fetch("http://127.0.0.1:8000/api/analytics/skip-reasons?days=30&limit=5")
        ]);

        if (!analyticsRes.ok || !breakdownRes.ok || !skipRes.ok) {
          throw new Error("Failed to fetch analytics data");
        }

        const [analyticsData, breakdownData, skipData] = await Promise.all([
          analyticsRes.json(),
          breakdownRes.json(),
          skipRes.json()
        ]);

        setAnalytics(analyticsData);
        setDecisionBreakdown(breakdownData);
        setSkipReasons(skipData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load analytics");
        console.error("Analytics fetch error:", err);
      } finally {
        setLoading(false);
      }
    };

    fetchAnalytics();
  }, []);

  if (loading) {
    return (
      <section className="status-panel">
        <div>
          <p className="eyebrow">ANALYTICS</p>
          <p>Loading analytics data...</p>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="status-panel">
        <div>
          <p className="eyebrow">ANALYTICS</p>
          <p className="error-text">{error}</p>
        </div>
      </section>
    );
  }

  if (!analytics) {
    return (
      <section className="status-panel">
        <div>
          <p className="eyebrow">ANALYTICS</p>
          <p>No analytics data available</p>
        </div>
      </section>
    );
  }

  return (
    <section className="analytics-section">
      <header>
        <p className="eyebrow">DECISION ANALYTICS</p>
        <h2>Agent Performance Overview</h2>
        <p className="period-text">Last {analytics.period_days} days</p>
      </header>

      {/* Summary Metrics */}
      <div className="analytics-grid">
        <div className="analytics-card">
          <div className="analytics-icon"><BarChart3 size={20} /></div>
          <div className="analytics-content">
            <p className="analytics-label">Jobs Discovered</p>
            <strong className="analytics-value">{analytics.discovered_jobs}</strong>
          </div>
        </div>

        <div className="analytics-card">
          <div className="analytics-icon success"><CheckCircle size={20} /></div>
          <div className="analytics-content">
            <p className="analytics-label">Applications Submitted</p>
            <strong className="analytics-value">{analytics.successful_applications}</strong>
            <p className="analytics-subtext">{analytics.success_rate}% success rate</p>
          </div>
        </div>

        <div className="analytics-card">
          <div className="analytics-icon warning"><XCircle size={20} /></div>
          <div className="analytics-content">
            <p className="analytics-label">Jobs Skipped</p>
            <strong className="analytics-value">{analytics.skipped_applications}</strong>
          </div>
        </div>

        <div className="analytics-card">
          <div className="analytics-icon attention"><AlertCircle size={20} /></div>
          <div className="analytics-content">
            <p className="analytics-label">Needs Attention</p>
            <strong className="analytics-value">{analytics.needs_attention}</strong>
          </div>
        </div>

        <div className="analytics-card">
          <div className="analytics-icon info"><TrendingUp size={20} /></div>
          <div className="analytics-content">
            <p className="analytics-label">AI Analyses</p>
            <strong className="analytics-value">{analytics.ai_analyses}</strong>
            <p className="analytics-subtext">{analytics.ai_requests} total requests</p>
          </div>
        </div>

        <div className="analytics-card">
          <div className="analytics-icon neutral"><Clock size={20} /></div>
          <div className="analytics-content">
            <p className="analytics-label">Discovery Runs</p>
            <strong className="analytics-value">{analytics.discovery_runs}</strong>
          </div>
        </div>
      </div>

      {/* Decision Breakdown */}
      {decisionBreakdown && (
        <div className="decision-breakdown">
          <h3>Decision Priority Distribution</h3>
          <div className="breakdown-bars">
            {Object.entries(decisionBreakdown.breakdown).map(([priority, count]) => {
              const percentage = decisionBreakdown.percentages[priority] || 0;
              const countDisplay = count || 0;
              return (
                <div key={priority} className="breakdown-item">
                  <div className="breakdown-label">
                    <span className="priority-badge">{priority.replace('_', ' ')}</span>
                    <span className="count-badge">{countDisplay}</span>
                  </div>
                  <div className="breakdown-bar">
                    <div 
                      className="breakdown-fill"
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                  <span className="percentage-text">{percentage.toFixed(1)}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Top Skip Reasons */}
      {skipReasons.length > 0 && (
        <div className="skip-reasons">
          <h3>Top Skip Reasons</h3>
          <div className="skip-reasons-list">
            {skipReasons.map((item, index) => (
              <div key={index} className="skip-reason-item">
                <span className="skip-reason-text">{item.reason}</span>
                <span className="skip-reason-count">{item.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
