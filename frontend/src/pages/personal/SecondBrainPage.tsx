import { useEffect, useState } from 'react';
import { askBrain, captureNote, fetchNotes, type Note } from '../../lib/personal-api';
import { OsError, OsShell } from './Shell';
import './personal.css';

export function SecondBrainPage() {
  const [notes, setNotes] = useState<Note[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    fetchNotes().then((data) => setNotes(data.notes)).catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <OsShell
      eyebrow="MEMORY"
      title="Second Brain"
      lede="Notes and ideas land here and, when the memory backend is available, in OpenJarvis memory too. Ask a question and the answer comes from what has been captured."
    >
      {error && <OsError message={error} />}
      <div className="os-grid">
        <form
          className="os-card"
          onSubmit={(event) => {
            event.preventDefault();
            if (!body.trim()) return;
            setBusy(true);
            captureNote({ title, body })
              .then(() => {
                setTitle('');
                setBody('');
                refresh();
              })
              .catch((err: Error) => setError(err.message))
              .finally(() => setBusy(false));
          }}
        >
          <label className="os-label" htmlFor="note-title">Title</label>
          <input id="note-title" className="os-field" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Pricing principle" />
          <label className="os-label" htmlFor="note-body" style={{ marginTop: 10 }}>Note</label>
          <textarea id="note-body" className="os-area" value={body} onChange={(event) => setBody(event.target.value)} placeholder="Charge for the outcome, not the hour." />
          <button className="os-button" style={{ marginTop: 12 }} type="submit" disabled={busy || !body.trim()}>Capture</button>
        </form>
        <form
          className="os-card"
          onSubmit={(event) => {
            event.preventDefault();
            if (!question.trim()) return;
            setBusy(true);
            askBrain(question)
              .then((data) => setAnswer(data.answer))
              .catch((err: Error) => setError(err.message))
              .finally(() => setBusy(false));
          }}
        >
          <label className="os-label" htmlFor="brain-ask">Ask from memory</label>
          <input id="brain-ask" className="os-field" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What did I decide about pricing?" />
          <button className="os-button" style={{ marginTop: 12 }} type="submit" disabled={busy || !question.trim()}>Ask</button>
          {answer && <p className="muted" style={{ marginTop: 14, whiteSpace: 'pre-wrap' }}>{answer}</p>}
        </form>
      </div>
      <div className="stack" style={{ marginTop: 16 }}>
        {notes.map((note) => (
          <article key={note.id} className="note-card">
            <div className="note-top">
              <h2>{note.title}</h2>
              <span className="chip">{note.memory_id ? 'In memory' : 'Local note'}</span>
            </div>
            <p className="muted" style={{ whiteSpace: 'pre-wrap' }}>{note.body}</p>
          </article>
        ))}
        {notes.length === 0 && <p className="muted">Nothing captured yet.</p>}
      </div>
    </OsShell>
  );
}
