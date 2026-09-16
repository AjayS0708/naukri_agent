import { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle, Database, ServerCrash } from "lucide-react";

export type AIProviderStatus =
    | "AVAILABLE"
    | "NOT_CONFIGURED"
    | "AUTH_ERROR"
    | "QUOTA_EXHAUSTED"
    | "UNAVAILABLE"
    | "ERROR";

export interface AIStatusResponse {
    provider: string;
    status: AIProviderStatus;
    model: string | null;
    requests: number;
    cached: number;
    errors: number;
    updated_at: string;
}

export function AIStatus() {
    const [status, setStatus] = useState<AIStatusResponse | null>(null);
    const [error, setError] = useState<Error | null>(null);
    const [loading, setLoading] = useState(true);

    const fetchStatus = async () => {
        try {
            const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
            const res = await fetch(`${BASE_URL}/api/ai/status`);
            if (!res.ok) throw new Error("Failed to fetch AI Status");
            const data = await res.json();
            setStatus(data);
            setError(null);
        } catch (err: any) {
            setError(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStatus();
        const interval = setInterval(fetchStatus, 30000);
        return () => clearInterval(interval);
    }, []);

    const getStatusIcon = (status?: AIProviderStatus) => {
        switch (status) {
            case "AVAILABLE": return <CheckCircle className="text-green-600 size-5" />;
            case "NOT_CONFIGURED": return <AlertTriangle className="text-yellow-500 size-5" />;
            case "QUOTA_EXHAUSTED": return <AlertTriangle className="text-orange-500 size-5" />;
            default: return <ServerCrash className="text-red-600 size-5" />;
        }
    };

    const getStatusColor = (status?: AIProviderStatus) => {
        switch (status) {
            case "AVAILABLE": return "text-green-700 bg-green-50 border-green-200";
            case "NOT_CONFIGURED": return "text-yellow-700 bg-yellow-50 border-yellow-200";
            case "QUOTA_EXHAUSTED": return "text-orange-700 bg-orange-50 border-orange-200";
            default: return "text-red-700 bg-red-50 border-red-200";
        }
    };

    if (loading) return <div className="p-4 border rounded-lg animate-pulse bg-gray-50 h-32"></div>;

    return (
        <div className="bg-[var(--color-white)] rounded-xl shadow-sm border border-[var(--color-border)] overflow-hidden">
            <div className="p-4 border-b border-[var(--color-border)] bg-[var(--color-bg)] flex justify-between items-center">
                <h2 className="text-lg font-semibold text-[var(--color-text)] flex gap-2 items-center">
                    <Database className="size-5 text-[var(--color-primary-blue)]" /> AI Engine Status
                </h2>
                {status && (
                    <div className={`px-2 py-1 flex gap-1 items-center rounded-md border text-sm font-medium ${getStatusColor(status.status)}`}>
                        {getStatusIcon(status.status)}
                        <span>{status.status.replace("_", " ")}</span>
                    </div>
                )}
            </div>

            <div className="p-4 flex flex-col gap-4">
                {error ? (
                    <div className="text-red-600 text-sm">{error.message}</div>
                ) : (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div className="flex flex-col">
                            <span className="text-[var(--color-text-secondary)] text-xs uppercase tracking-wider font-semibold">Provider</span>
                            <span className="text-[var(--color-text)] font-medium capitalize">{status?.provider || "Unknown"}</span>
                        </div>
                        <div className="flex flex-col">
                            <span className="text-[var(--color-text-secondary)] text-xs uppercase tracking-wider font-semibold">Model</span>
                            <span className="text-[var(--color-text)] font-medium">{status?.model || "Not configured"}</span>
                        </div>
                        <div className="flex flex-col">
                            <span className="text-[var(--color-text-secondary)] text-xs uppercase tracking-wider font-semibold">Engine Activity</span>
                            <span className="text-[var(--color-text)] font-medium flex gap-2 items-center">
                                <Activity className="size-4 text-[var(--color-primary-blue)]" /> {status?.requests || 0} Requests
                            </span>
                        </div>
                        <div className="flex flex-col">
                            <span className="text-[var(--color-text-secondary)] text-xs uppercase tracking-wider font-semibold">Errors Limit</span>
                            <span className="text-[var(--color-text)] font-medium">{status?.errors || 0} Issues</span>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
