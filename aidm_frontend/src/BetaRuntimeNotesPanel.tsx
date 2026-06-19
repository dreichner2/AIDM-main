import { X } from 'lucide-react'

export function BetaRuntimeNotesPanel({ onClose }: { onClose: () => void }) {
  return (
    <section
      id="beta-runtime-known-limitations"
      className="beta-runtime-notes-panel"
      role="note"
      aria-label="Known beta limitations"
    >
      <div>
        <strong>Known Limitations</strong>
        <button
          type="button"
          aria-label="Close beta notes"
          onClick={onClose}
        >
          <X size={14} />
        </button>
      </div>
      <ul>
        <li>Closed beta is for controlled playtests, not unrestricted public hosting.</li>
        <li>Fallback provider, missing provider keys, unavailable TTS, and process-local provider changes can degrade sessions.</li>
        <li>Hosted cookie auth, CSRF, Socket.IO, and restore behavior still need target-specific evidence before wider invites.</li>
        <li>Campaign packs can include hidden authored content that players should not see at session start.</li>
        <li>Operator support bundles can expose session IDs, provider/model metadata, and audit references.</li>
      </ul>
    </section>
  )
}

export default BetaRuntimeNotesPanel
