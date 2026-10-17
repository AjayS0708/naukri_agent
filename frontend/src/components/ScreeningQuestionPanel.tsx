import { useEffect, useRef, useState } from "react";
import { HelpCircle, LoaderCircle, MessageSquareWarning, SkipForward } from "lucide-react";
import { answerPendingQuestion, getPendingQuestion } from "../services/api";
import type { AnswerQuestionRequest, PendingQuestion } from "../types/api";

interface ScreeningQuestionPanelProps {
  /** True while the active run is blocked waiting for a screening answer. */
  active: boolean;
  /** Called after the answer/skip was accepted, with the user-facing notice. */
  onAnswered: (notice: string) => void;
  heading?: string;
}

/**
 * Shared screening-question lifecycle (E5-R21/R32): fetches the pending
 * question while the run waits, submits an answer or job-skip through the
 * existing contract, and self-heals on 409 (answered/changed questions).
 * Answers are never preselected.
 */
export function ScreeningQuestionPanel({ active, onAnswered, heading = "Screening question" }: ScreeningQuestionPanelProps) {
  const [question, setQuestion] = useState<PendingQuestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [remember, setRemember] = useState(true);
  const [rememberAll, setRememberAll] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const onAnsweredRef = useRef(onAnswered);
  onAnsweredRef.current = onAnswered;

  useEffect(() => {
    if (!active) {
      setQuestion(null);
      setError(null);
      setLoading(false);
      setAnswerText("");
      return;
    }
    let stopped = false;
    let timer: number | undefined;
    setLoading(true);

    const fetchQuestion = async () => {
      try {
        const data = await getPendingQuestion();
        if (stopped) return;
        setQuestion(data);
        setError(data.found ? null : "The question is not available yet — retrying…");
      } catch {
        if (!stopped) setError("The question could not be loaded — retrying…");
      } finally {
        if (!stopped) {
          setLoading(false);
          timer = window.setTimeout(fetchQuestion, 4000);
        }
      }
    };
    void fetchQuestion();

    return () => {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [active]);

  if (!active) return null;

  const submit = async (skip: boolean) => {
    if (!question?.pending_question_id || submitting) return;
    if (!skip && !answerText.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const request: AnswerQuestionRequest = skip
        ? { pending_question_id: question.pending_question_id, skip: true }
        : {
            pending_question_id: question.pending_question_id,
            answer: answerText.trim(),
            remember,
            scope: rememberAll ? "GLOBAL" : "JOB",
            allow_global_reuse: remember && rememberAll,
          };
      await answerPendingQuestion(request);
      setQuestion(null);
      setAnswerText("");
      setRememberAll(false);
      onAnsweredRef.current(
        skip
          ? "Job skipped — the run is resuming with the next job."
          : "Answer received — the run is resuming.",
      );
    } catch (err: unknown) {
      const status = (err as { status?: number } | null)?.status;
      const message = (err as { message?: string } | null)?.message;
      if (status === 409) {
        setError("This question was already answered or has changed — refreshing…");
        const fresh = await getPendingQuestion().catch(() => null);
        setQuestion(fresh);
      } else {
        setError(message ?? "The answer could not be submitted. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const hasQuestion = Boolean(question?.found && question.question_text);

  return (
    <section className="question-panel" role="alert" aria-live="assertive">
      <div className="question-head">
        <span className="question-icon">
          <MessageSquareWarning size={18} />
        </span>
        <div>
          <p className="eyebrow">
            {heading}
            {question?.job_title ? ` — ${question.job_title}` : ""}
            {question?.employer ? ` · ${question.employer}` : ""}
          </p>
          <p className="question-status">
            <span className="pulse-dot" aria-hidden />
            Waiting for your answer — the run is paused
          </p>
        </div>
      </div>

      {loading && !hasQuestion ? (
        <p className="question-loading">
          <LoaderCircle size={15} className="spin" /> Loading the question…
        </p>
      ) : hasQuestion ? (
        <div className="question-body">
          <p className="question-text">
            <strong>{question!.question_text}</strong>
          </p>
          {question!.options && question!.options.length > 0 ? (
            <select
              className="question-input"
              value={answerText}
              onChange={(e) => setAnswerText(e.target.value)}
              aria-label="Choose an answer"
            >
              <option value="">Select an answer…</option>
              {question!.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : (
            <input
              className="question-input"
              type="text"
              value={answerText}
              onChange={(e) => setAnswerText(e.target.value)}
              placeholder="Type your answer"
              aria-label="Your answer"
            />
          )}
          <div className="question-checks">
            <label>
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              Save this answer for future applications
            </label>
            <label>
              <input
                type="checkbox"
                checked={rememberAll}
                disabled={!remember}
                onChange={(e) => setRememberAll(e.target.checked)}
              />
              Reuse it for all jobs (salary, notice, relocation, …)
            </label>
          </div>
          {error && <p className="error-text">{error}</p>}
          <div className="question-actions">
            <button
              className="btn btn-primary"
              onClick={() => void submit(false)}
              disabled={submitting || !answerText.trim()}
            >
              {submitting ? <LoaderCircle size={15} className="spin" /> : <HelpCircle size={15} />}
              {submitting ? "Submitting…" : "Answer & resume"}
            </button>
            <button className="btn btn-secondary" onClick={() => void submit(true)} disabled={submitting}>
              <SkipForward size={15} />
              Skip this job
            </button>
          </div>
        </div>
      ) : (
        <p className="question-loading">{error ?? "Waiting for the question…"}</p>
      )}
    </section>
  );
}
