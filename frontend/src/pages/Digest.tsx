import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Inbox,
  MessageSquare,
  CalendarDays,
  Music,
  Twitter,
  Loader2,
  Zap,
  AlertCircle,
  Clock,
  BookOpen,
  Users,
  CheckSquare,
  Mail,
  Lock,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import { useZODigest } from "@/hooks/useZODigest";

// ── Agent registry ────────────────────────────────────────────────────────────
// `live` = wired to a real backend. `placeholder` = UI only, not wired.

const AGENTS = [
  {
    id: "email",
    label: "Email",
    sublabel: "via ZO",
    icon: Inbox,
    color: "#FF6B6B",
    glow: "rgba(255,107,107,0.25)",
    status: "live" as const,
    description: "Parse NTU Outlook emails into a structured academic digest.",
  },
  {
    id: "discord",
    label: "Discord",
    sublabel: "coming soon",
    icon: MessageSquare,
    color: "#5865F2",
    glow: "rgba(88,101,242,0.2)",
    status: "placeholder" as const,
    description: "Surface study-group messages and assignment reminders from your Discord servers.",
  },
  {
    id: "x",
    label: "X / Twitter",
    sublabel: "coming soon",
    icon: Twitter,
    color: "#1D9BF0",
    glow: "rgba(29,155,240,0.2)",
    status: "placeholder" as const,
    description: "Track academic Twitter threads, professor posts, and NTU announcements.",
  },
  {
    id: "calendar",
    label: "Calendar",
    sublabel: "coming soon",
    icon: CalendarDays,
    color: "#34D399",
    glow: "rgba(52,211,153,0.2)",
    status: "placeholder" as const,
    description: "Sync Google or Outlook calendar events into your Atlas timeline.",
  },
  {
    id: "spotify",
    label: "Spotify",
    sublabel: "coming soon",
    icon: Music,
    color: "#1DB954",
    glow: "rgba(29,185,84,0.2)",
    status: "placeholder" as const,
    description: "Auto-generate focus playlists based on your current study workload.",
  },
] as const;

type AgentId = (typeof AGENTS)[number]["id"];

// ── Section config for the digest result grid ─────────────────────────────────

const SECTIONS = [
  { key: "deadlines",       label: "Deadlines",       icon: Clock,       color: "#FF6B6B" },
  { key: "exams",           label: "Exams",            icon: BookOpen,    color: "#F59E0B" },
  { key: "meetings",        label: "Meetings",         icon: Users,       color: "#818CF8" },
  { key: "upcoming_events", label: "Upcoming Events",  icon: CalendarDays,color: "#34D399" },
  { key: "action_items",    label: "Action Items",     icon: CheckSquare, color: "#60A5FA" },
  { key: "needs_reply",     label: "Needs Reply",      icon: Mail,        color: "#F472B6" },
] as const;

// ── Component ─────────────────────────────────────────────────────────────────

export function Digest() {
  const [activeAgent, setActiveAgent] = useState<AgentId>("email");
  const [emailText, setEmailText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { parseEmails, digest, loading } = useZODigest();

  const handleParse = async () => {
    setError(null);
    try {
      await parseEmails(emailText);
    } catch {
      setError("Could not reach the ZO agent. Check that the backend is running and ZO_API_KEY is set.");
    }
  };

  return (
    <div className="w-full h-full flex flex-col px-10 pt-10 pb-6 overflow-y-auto">
      {/* ── Header ── */}
      <div className="mb-8">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-1.5 h-1.5 rounded-full bg-[#FF6B6B] animate-pulse" />
          <span className="text-[10px] font-mono tracking-[0.25em] text-white/30 uppercase">
            Agent Feeds
          </span>
        </div>
        <h1 className="text-2xl font-semibold text-white/90 tracking-tight">Daily Digest</h1>
        <p className="text-[13px] text-white/40 mt-1">
          Connect agents to surface intelligence from your digital life into Atlas.
        </p>
      </div>

      {/* ── Agent source cards ── */}
      <div className="flex gap-3 mb-8 flex-wrap">
        {AGENTS.map((agent) => {
          const Icon = agent.icon;
          const isActive = activeAgent === agent.id;
          const isLive = agent.status === "live";

          return (
            <button
              key={agent.id}
              onClick={() => isLive && setActiveAgent(agent.id)}
              disabled={!isLive}
              className={`
                relative flex flex-col gap-2 p-4 rounded-2xl border transition-all duration-300 text-left w-[160px] shrink-0
                ${isActive
                  ? "border-white/20 bg-white/[0.07]"
                  : isLive
                    ? "border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.05] cursor-pointer"
                    : "border-white/[0.05] bg-white/[0.02] cursor-not-allowed opacity-60"
                }
              `}
              style={isActive ? { boxShadow: `0 0 24px ${agent.glow}` } : undefined}
            >
              {/* Lock badge for placeholder agents */}
              {!isLive && (
                <div className="absolute top-3 right-3">
                  <Lock size={10} className="text-white/20" />
                </div>
              )}

              {/* Live badge */}
              {isLive && (
                <div className="absolute top-3 right-3 flex items-center gap-1">
                  <div
                    className="w-1.5 h-1.5 rounded-full animate-pulse"
                    style={{ backgroundColor: agent.color }}
                  />
                </div>
              )}

              <div
                className="w-9 h-9 rounded-xl flex items-center justify-center"
                style={{ backgroundColor: `${agent.color}20`, border: `1px solid ${agent.color}30` }}
              >
                <Icon size={18} style={{ color: agent.color }} />
              </div>

              <div>
                <p className="text-[13px] font-medium text-white/80">{agent.label}</p>
                <p className="text-[10px] text-white/30 mt-0.5">{agent.sublabel}</p>
              </div>
            </button>
          );
        })}
      </div>

      {/* ── Active agent panel ── */}
      <AnimatePresence mode="wait">
        {activeAgent === "email" && (
          <motion.div
            key="email-panel"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }}
            className="flex-1 flex flex-col gap-6"
          >
            {/* Description */}
            <div className="flex items-start gap-3 p-4 rounded-2xl border border-white/[0.07] bg-white/[0.03]">
              <Zap size={16} className="text-[#FF6B6B] mt-0.5 shrink-0" />
              <p className="text-[13px] text-white/50 leading-relaxed">
                Paste your NTU Outlook email content below. Atlas will use the{" "}
                <span className="text-white/70">ZO agent</span> to extract deadlines, exams, meetings,
                action items, and anything that needs a reply.
              </p>
            </div>

            {/* Input */}
            <div className="flex flex-col gap-3">
              <textarea
                value={emailText}
                onChange={(e) => setEmailText(e.target.value)}
                placeholder="Paste email content here — subject lines, message bodies, forwarded threads…"
                rows={7}
                className="w-full rounded-2xl border border-white/[0.08] bg-white/[0.04] px-4 py-3 text-[13px] text-white/80 placeholder-white/20 resize-none focus:outline-none focus:border-[#FF6B6B]/40 transition-colors"
              />
              <div className="flex items-center gap-3">
                <button
                  onClick={handleParse}
                  disabled={loading || !emailText.trim()}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#FF6B6B]/20 border border-[#FF6B6B]/30 text-[#FF8A80] text-[13px] font-medium hover:bg-[#FF6B6B]/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {loading ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  {loading ? "Scanning…" : "Scan Emails"}
                </button>
                {digest && !loading && (
                  <span className="text-[11px] text-white/30">
                    Last scan complete
                  </span>
                )}
              </div>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-start gap-2 p-3 rounded-xl border border-red-500/20 bg-red-500/10">
                <AlertCircle size={14} className="text-red-400 mt-0.5 shrink-0" />
                <p className="text-[12px] text-red-300">{error}</p>
              </div>
            )}

            {/* Results */}
            <AnimatePresence>
              {digest && (
                <motion.div
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.4 }}
                  className="flex flex-col gap-4"
                >
                  {/* Summary */}
                  <div className="p-5 rounded-2xl border border-white/[0.08] bg-white/[0.04]">
                    <div className="flex items-center gap-2 mb-3">
                      <Inbox size={14} className="text-[#FF6B6B]" />
                      <span className="text-[11px] font-mono tracking-[0.2em] text-white/40 uppercase">
                        Summary
                      </span>
                    </div>
                    <p className="text-[14px] text-white/70 leading-relaxed">{digest.summary}</p>
                  </div>

                  {/* Section grid */}
                  <div className="grid grid-cols-2 gap-3">
                    {SECTIONS.map(({ key, label, icon: SectionIcon, color }) => {
                      const items = digest[key as keyof typeof digest] as string[];
                      if (!items || items.length === 0) return null;

                      return (
                        <div
                          key={key}
                          className="p-4 rounded-2xl border border-white/[0.07] bg-white/[0.03]"
                        >
                          <div className="flex items-center gap-2 mb-3">
                            <SectionIcon size={13} style={{ color }} />
                            <span
                              className="text-[10px] font-mono tracking-[0.2em] uppercase"
                              style={{ color: `${color}99` }}
                            >
                              {label}
                            </span>
                            <span className="ml-auto text-[10px] text-white/20">{items.length}</span>
                          </div>
                          <ul className="flex flex-col gap-1.5">
                            {items.map((item, i) => (
                              <li key={i} className="flex items-start gap-2">
                                <ChevronRight size={11} className="text-white/20 mt-[3px] shrink-0" />
                                <span className="text-[12px] text-white/60 leading-relaxed">{item}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      );
                    })}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
