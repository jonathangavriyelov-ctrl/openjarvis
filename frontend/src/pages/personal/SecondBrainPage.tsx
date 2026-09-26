import { useEffect, useState } from 'react';
import { askBrain, captureNote, fetchBriefing, fetchNotes, pullDrive, type Note } from '../../lib/personal-api';
import { OsError, OsShell, useDeskWorld } from './Shell';
import './personal.css';

export function SecondBrainPage() {
  const deskWorld = useDeskWorld();
  const [notes, setNotes] = useState<Note[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [question, setQuestion] = useState('');
  const [driveQuery, setDriveQuery] = useState('');
  const [driveNote, setDriveNote] = useState('');
  const [answer, setAnswer] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    fetchNotes(deskWorld).then((data) => setNotes(data.notes)).catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    refresh();
    if (!deskWorld) {
      setDriveNote('Open a world before pulling Drive docs.');
      return;
    }
    fetchBriefing(deskWorld)
      .then((data) => {
        if (!data.connected) setDriveNote('Google Drive is not connected.');
        else setDriveNote('');
      })
      .catch(() => {});
  }, [deskWorld]);

  return (
    <OsShell
      eyebrow="MEMORY"
      title="Second Brain"
      lede="Notes and ideas land here and, when the memory backend is available, in OpenJarvis memory too. Pull matching Google Drive docs into the same list. Ask a question and the answer comes from what has been captured."
    >
      {error && <OsError message={error} />}
      <div className="os-grid">
        <form
          className="os-card"
          onSubmit={(event) => {
            event.preventDefault();
            if (!body.trim()) return;
            setBusy(true);
            captureNote({ title, body, world_id: deskWorld || '' })
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
            askBrain(question, deskWorld)
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
      <form
        className="os-card"
        style={{ marginTop: 16 }}
        onSubmit={(event) => {
          event.preventDefault();
          if (!driveQuery.trim()) return;
          setBusy(true);
          setDriveNote('');
          pullDrive(driveQuery, deskWorld)
            .then((data) => {
              if (data.detail) {
                setDriveNote(data.detail);
              } else if (!data.connected) {
                setDriveNote('Google Drive is not connected.');
              } else if (data.notes.length === 0) {
                setDriveNote('No new matching Drive docs.');
              } else {
                setDriveNote(`Saved ${data.notes.length} Drive doc${data.notes.length === 1 ? '' : 's'}.`);
              }
              setDriveQuery('');
              refresh();
            })
            .catch((err: Error) => setError(err.message))
            .finally(() => setBusy(false));
        }}
      >
        <label className="os-label" htmlFor="drive-query">Pull from Drive</label>
        {driveNote && (
          <p role="status" style={{ margin: '8px 0 12px', color: '#f5c16c' }}>{driveNote}</p>
        )}
        <input
          id="drive-query"
          className="os-field"
          value={driveQuery}
          onChange={(event) => setDriveQuery(event.target.value)}
          placeholder="pricing notes"
        />
        <button className="os-button" style={{ marginTop: 12 }} type="submit" disabled={busy || !driveQuery.trim()}>
          Pull from Drive
        </button>
      </form>
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
