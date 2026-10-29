import { Fragment, useCallback, useEffect, useState } from "react";
import {
  cancelClass, createClass, fetchAvailability, fetchClass, fetchClassTypes, fetchCoaches, fetchSchedule, updateClass,
} from "../../api/classes.js";
import { BUTTON_COLORS } from "../../styles/buttonColors.js";
import SegmentedControl from "../SegmentedControl.jsx";
import ClassTypeManager from "./ClassTypeManager.jsx";
import PTHoursManager, { CancelSessionDialog } from "./PTHoursManager.jsx";
import { addDays, formatDay, formatLongDay, weekLabel } from "./dates.js";
import useServerClock, { offsetLabel } from "./useServerClock.js";

// User story: "As a branch manager, I want to create and edit class schedules
// and assign coaches to time slots, so that I can build the weekly class
// calendar for my branch."
//
// A real Monday-to-Sunday calendar. Which days are past comes from the
// server's clock (Beirut time): past days, and classes that have already
// started, are view-only - the server refuses changes to them too. Several
// classes can share a time slot as long as the coaches (and studios) differ;
// the server checks every clash, including a coach teaching at another
// branch. The front desk (manage_members) sees the same calendar read-only.
//
// Every time on the calendar is Beirut time (the server's TIME_ZONE): the
// clock above it runs from the server's "now", and the week reloads every
// minute so classes turn "in progress"/"finished" and days turn past on time.
//
// Each class is of a class type (ClassTypeManager.jsx), whose maximum
// capacity caps the class's spots - "set maximum capacity per class type,
// so that I can prevent overbooking and keep sessions safe."

const DURATIONS = [15, 20, 30, 45, 60, 75, 90, 105, 120, 150, 180, 240];
const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, "0"));
const MINUTES = Array.from({ length: 12 }, (_, i) => String(i * 5).padStart(2, "0"));
const REFRESH_MS = 60000;
const COACH_COLORS = ["#124096", "#129638", "#b45309", "#7c3aed", "#0e7490", "#be185d"];

const coachColor = (coachId) => COACH_COLORS[coachId % COACH_COLORS.length];
const toMinutes = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};
const fromMinutes = (total) => `${String(Math.floor(total / 60) % 24).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;

export default function ClassSchedule() {
  const [week, setWeek] = useState(null); // any date in the week shown; null = this week
  const [branch, setBranch] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [coaches, setCoaches] = useState([]);
  const [detailId, setDetailId] = useState(null);
  const [editor, setEditor] = useState(null); // { mode: "create", date } | { mode: "edit", gymClass, seriesFollowing }
  const [cancelTarget, setCancelTarget] = useState(null);
  const [notice, setNotice] = useState(null);
  const [view, setView] = useState("calendar");
  const [classTypes, setClassTypes] = useState([]);
  const [ptDetail, setPtDetail] = useState(null);
  const [ptCancel, setPtCancel] = useState(null);
  const clock = useServerClock(data?.nowIso, data?.timeZone);

  const load = useCallback(() => {
    setError(null);
    return fetchSchedule({ week, branch })
      .then((body) => {
        setData(body);
        if (!branch) setBranch(body.branch);
      })
      .catch((err) => setError(err.message));
  }, [week, branch]);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!data?.branch) return;
    fetchCoaches(data.branch)
      .then((body) => setCoaches(body.results))
      .catch(() => setCoaches([]));
  }, [data?.branch]);

  const loadTypes = useCallback(() => {
    if (!data?.branch) return;
    fetchClassTypes(data.branch)
      .then((body) => setClassTypes(body.results))
      .catch(() => setClassTypes([]));
  }, [data?.branch]);

  useEffect(() => {
    loadTypes();
  }, [loadTypes]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 5000);
    return () => clearTimeout(timer);
  }, [notice]);

  if (!data) {
    return (
      <div style={styles.page}>
        <h1 style={styles.title}>Class Schedule</h1>
        {error ? <div style={styles.errorBox}>Couldn't load the schedule: {error}</div> : <p style={styles.muted}>Loading...</p>}
      </div>
    );
  }

  const byDay = Object.fromEntries(data.days.map((d) => [d.date, []]));
  data.classes.forEach((c) => byDay[c.date]?.push(c));
  Object.values(byDay).forEach((list) => list.sort((a, b) => a.startTime.localeCompare(b.startTime)));
  const ptByDay = {};
  (data.ptSessions || []).forEach((s) => (ptByDay[s.date] = [...(ptByDay[s.date] || []), s]));
  const isThisWeek = data.days.some((d) => d.isToday);

  function afterSave(message) {
    setEditor(null);
    setCancelTarget(null);
    setDetailId(null);
    setNotice(message);
    load();
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Class Schedule</h1>
          <p style={styles.subtitle}>
            {data.canEdit
              ? "Build the week's classes and assign coaches. Past days are view-only."
              : "This week's classes at your branch. Only a branch manager can change them."}
          </p>
        </div>
        {data.branches.length > 1 ? (
          <label style={styles.branchPicker}>
            <span style={styles.fieldLabel}>Branch</span>
            <select value={branch} onChange={(e) => setBranch(e.target.value)} style={styles.select}>
              {data.branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <span style={styles.branchChip}>{data.branch}</span>
        )}
      </div>

      {notice && <div style={styles.successBox}>{notice}</div>}
      {error && <div style={styles.errorBox}>{error}</div>}

      <div style={styles.viewBar}>
        <div style={styles.viewSwitch}>
          <SegmentedControl
            ariaLabel="View"
            options={[
              { value: "calendar", label: "Weekly calendar" },
              { value: "types", label: "Class types" },
              { value: "pt", label: "Private training" },
            ]}
            value={view}
            onChange={(next) => {
              setView(next);
              if (next === "calendar") {
                loadTypes();
                load();
              }
            }}
          />
        </div>
        <span style={styles.clock} title={`All times are ${data.timeZone} (${offsetLabel(data.utcOffset)})`}>
          <span style={styles.clockLabel}>Beirut time</span>
          <span style={styles.clockTime}>{clock.time}</span>
          <span style={styles.clockDay}>
            {clock.day} · {offsetLabel(data.utcOffset)}
          </span>
        </span>
      </div>

      {view === "types" && (
        <ClassTypeManager
          branch={data.branch}
          onChanged={() => {
            loadTypes();
            load();
          }}
        />
      )}
      {view === "pt" && <PTHoursManager branch={data.branch} onChanged={load} />}
      {view === "calendar" && (
      <>
      <div style={styles.toolbar}>
        <div style={styles.weekNav}>
          <button type="button" onClick={() => setWeek(addDays(data.weekStart, -7))} style={styles.navButton} aria-label="Previous week">
            ‹
          </button>
          <button type="button" onClick={() => setWeek(null)} disabled={isThisWeek} style={styles.todayButton}>
            This week
          </button>
          <button type="button" onClick={() => setWeek(addDays(data.weekStart, 7))} style={styles.navButton} aria-label="Next week">
            ›
          </button>
          <span style={styles.weekLabel}>{weekLabel(data.weekStart, data.weekEnd)}</span>
        </div>
        <label style={styles.jump}>
          <span style={styles.fieldLabel}>Go to</span>
          <input
            type="date"
            value=""
            onChange={(e) => e.target.value && setWeek(e.target.value)}
            style={styles.select}
            aria-label="Go to date"
          />
        </label>
      </div>

      <div style={styles.legend}>
        <span style={styles.legendItem}>
          <span style={{ ...styles.swatch, ...styles.swatchPast }} /> Past · view only
        </span>
        <span style={styles.legendItem}>
          <span style={{ ...styles.swatch, ...styles.swatchToday }} /> Today · {formatDay(data.today)}
        </span>
        <span style={styles.legendItem}>
          <span style={{ ...styles.swatch, ...styles.swatchUpcoming }} /> Upcoming
        </span>
        <span style={styles.legendItem}>Colour = coach</span>
        <span style={styles.legendItem}>All times are Beirut time</span>
      </div>

      <div style={styles.grid}>
        {data.days.map((day) => (
          <DayColumn
            key={day.date}
            day={day}
            classes={byDay[day.date]}
            ptSessions={ptByDay[day.date] || []}
            canEdit={data.canEdit}
            onOpen={(c) => setDetailId(c.id)}
            onOpenPt={setPtDetail}
            onAdd={() => setEditor({ mode: "create", date: day.date })}
          />
        ))}
      </div>
      </>
      )}

      {ptDetail && (
        <Modal title="Private training" onClose={() => setPtDetail(null)}>
          <div style={styles.detailGrid}>
            <Info label="When" value={`${formatLongDay(ptDetail.date)} · ${ptDetail.startTime}–${ptDetail.endTime}`} />
            <Info label="Coach" value={ptDetail.coachName} />
            <Info label="Member" value={`${ptDetail.memberName} (ID ${ptDetail.memberId})`} />
            <Info label="Note" value={ptDetail.note || "—"} />
          </div>
          {ptDetail.state !== "upcoming" && (
            <div style={styles.lockBox}>
              This session {ptDetail.state === "finished" ? "has already taken place" : "is in progress"} - it&apos;s view-only.
            </div>
          )}
          {data.canEdit && ptDetail.state === "upcoming" && (
            <div style={styles.actions}>
              <button
                type="button"
                onClick={() => {
                  setPtCancel(ptDetail);
                  setPtDetail(null);
                }}
                style={styles.dangerButton}
              >
                Cancel session
              </button>
            </div>
          )}
        </Modal>
      )}
      {ptCancel && (
        <CancelSessionDialog
          session={ptCancel}
          onClose={() => setPtCancel(null)}
          onCancelled={(s) => {
            setPtCancel(null);
            setNotice(`${s.memberName}'s private session with ${s.coachName} at ${s.startTime} was cancelled.`);
            load();
          }}
        />
      )}
      {detailId && (
        <ClassDetails
          classId={detailId}
          onClose={() => setDetailId(null)}
          onEdit={(gymClass, seriesFollowing) => {
            setDetailId(null);
            setEditor({ mode: "edit", gymClass, seriesFollowing });
          }}
          onCancel={(gymClass, seriesFollowing) => {
            setDetailId(null);
            setCancelTarget({ gymClass, seriesFollowing });
          }}
        />
      )}
      {editor && (
        <ClassForm
          editor={editor}
          branch={data.branch}
          today={data.today}
          coaches={coaches}
          classTypes={classTypes}
          onManageTypes={() => {
            setEditor(null);
            setView("types");
          }}
          onClose={() => setEditor(null)}
          onSaved={(classes) =>
            afterSave(
              editor.mode === "create"
                ? classes.length > 1
                  ? `${classes[0].name} scheduled every week for ${classes.length} weeks.`
                  : `${classes[0].name} scheduled on ${formatDay(classes[0].date)} at ${classes[0].startTime}.`
                : `${classes[0].name} updated${classes.length > 1 ? ` (${classes.length} classes)` : ""}.`,
            )
          }
        />
      )}
      {cancelTarget && (
        <CancelDialog
          target={cancelTarget}
          onClose={() => setCancelTarget(null)}
          onCancelled={(result) =>
            afterSave(
              `${cancelTarget.gymClass.name} cancelled${result.classes.length > 1 ? ` (${result.classes.length} classes)` : ""}` +
                (result.releasedBookings ? ` - ${result.releasedBookings} booking(s) released.` : "."),
            )
          }
        />
      )}
    </div>
  );
}

function DayColumn({ day, classes, ptSessions, canEdit, onOpen, onOpenPt, onAdd }) {
  const columnStyle = day.isToday ? styles.dayToday : day.isPast ? styles.dayPast : styles.dayUpcoming;
  const items = [
    ...classes.map((c) => ({
      key: `class-${c.id}`,
      startTime: c.startTime,
      node: <ClassCard gymClass={c} dayIsPast={day.isPast} onOpen={() => onOpen(c)} />,
    })),
    ...ptSessions.map((s) => ({
      key: `pt-${s.id}`,
      startTime: s.startTime,
      node: <PtCard session={s} dayIsPast={day.isPast} onOpen={() => onOpenPt(s)} />,
    })),
  ].sort((a, b) => a.startTime.localeCompare(b.startTime));
  return (
    <section style={{ ...styles.day, ...columnStyle }} aria-label={formatLongDay(day.date)}>
      <div style={styles.dayHeader}>
        <span style={{ ...styles.dayName, color: day.isPast ? "#8a8a93" : "#1a1a1a" }}>{formatDay(day.date)}</span>
        {day.isToday && <span style={styles.todayBadge}>Today</span>}
        {day.isPast && <span style={styles.pastBadge}>Past · view only</span>}
      </div>

      {items.length === 0 && <div style={styles.emptyDay}>{day.isPast ? "No classes" : "Nothing scheduled"}</div>}
      {items.map((item) => (
        <Fragment key={item.key}>{item.node}</Fragment>
      ))}

      {canEdit && !day.isPast && (
        <button type="button" onClick={onAdd} style={styles.addButton}>
          + Add class
        </button>
      )}
    </section>
  );
}

function ClassCard({ gymClass: c, dayIsPast, onOpen }) {
  const cancelled = c.state === "cancelled";
  const done = c.state === "finished" || dayIsPast;
  const full = c.state === "upcoming" && c.spotsLeft === 0;
  return (
    <button
      type="button"
      onClick={onOpen}
      style={{
        ...styles.card,
        borderLeftColor: cancelled ? "#d0d0d5" : coachColor(c.coachId),
        ...(done || cancelled ? styles.cardMuted : null),
      }}
      aria-label={`${c.name} ${c.startTime} to ${c.endTime} with ${c.coachName}`}
    >
      <span style={styles.cardTime}>
        {c.startTime}–{c.endTime}
      </span>
      <span style={{ ...styles.cardName, textDecoration: cancelled ? "line-through" : "none" }}>{c.name}</span>
      <span style={styles.cardMeta}>
        {c.coachName}
        {c.room && ` · ${c.room}`}
      </span>
      <span style={styles.cardFooter}>
        <span style={styles.cardSpots}>
          {c.booked}/{c.capacity} booked
        </span>
        {c.state === "in_progress" && <span style={{ ...styles.stateTag, ...styles.tagLive }}>In progress</span>}
        {c.state === "finished" && <span style={{ ...styles.stateTag, ...styles.tagDone }}>Finished</span>}
        {cancelled && <span style={{ ...styles.stateTag, ...styles.tagCancelled }}>Cancelled</span>}
        {full && <span style={{ ...styles.stateTag, ...styles.tagFull }}>Full</span>}
      </span>
      {!c.coachActive && c.editable && <span style={styles.coachWarning}>Coach deactivated - reassign</span>}
    </button>
  );
}

// A booked private training session on the week, so a coach's whole day shows.
function PtCard({ session: s, dayIsPast, onOpen }) {
  const done = s.state === "finished" || dayIsPast;
  return (
    <button
      type="button"
      onClick={onOpen}
      style={{ ...styles.card, ...styles.ptCard, borderLeftColor: coachColor(s.coachId), ...(done ? styles.cardMuted : null) }}
      aria-label={`Private training ${s.startTime} to ${s.endTime} with ${s.coachName}`}
    >
      <span style={styles.cardTime}>
        {s.startTime}–{s.endTime}
      </span>
      <span style={styles.cardName}>Private training</span>
      <span style={styles.cardMeta}>
        {s.coachName} · {s.memberName}
      </span>
      {s.state === "in_progress" && <span style={{ ...styles.stateTag, ...styles.tagLive }}>In progress</span>}
      {s.state === "finished" && <span style={{ ...styles.stateTag, ...styles.tagDone }}>Finished</span>}
    </button>
  );
}

function ClassDetails({ classId, onClose, onEdit, onCancel }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchClass(classId)
      .then(setDetail)
      .catch((err) => setError(err.message));
  }, [classId]);

  const booked = detail?.roster.filter((r) => r.status === "Booked") || [];
  const released = detail?.roster.filter((r) => r.status !== "Booked") || [];

  return (
    <Modal title={detail ? detail.name : "Class"} onClose={onClose} wide>
      {error && <div style={styles.errorBox}>{error}</div>}
      {!detail && !error && <p style={styles.muted}>Loading...</p>}
      {detail && (
        <>
          <div style={styles.detailGrid}>
            <Info label="When" value={`${formatLongDay(detail.date)} · ${detail.startTime}–${detail.endTime} (${detail.durationMinutes} min)`} />
            <Info label="Coach" value={detail.coachActive ? detail.coachName : `${detail.coachName} (deactivated)`} />
            <Info label="Studio" value={detail.room || "—"} />
            <Info
              label="Booked"
              value={`${detail.booked} of ${detail.capacity} spots` +
                (detail.capacity < detail.maxCapacity ? ` (${detail.name} allows up to ${detail.maxCapacity})` : "")}
            />
            {detail.seriesId && <Info label="Repeats" value="Every week" />}
            {detail.description && <Info label="About" value={detail.description} />}
          </div>

          {detail.state === "finished" && (
            <div style={styles.lockBox}>This class has already taken place - it's view-only.</div>
          )}
          {detail.state === "in_progress" && <div style={styles.lockBox}>This class is in progress - it's view-only.</div>}
          {detail.state === "cancelled" && (
            <div style={styles.errorBox}>Cancelled{detail.cancelReason ? `: ${detail.cancelReason}` : "."}</div>
          )}

          <h3 style={styles.rosterTitle}>
            {detail.state === "finished" ? "Attendance" : "Booked members"} ({booked.length})
          </h3>
          {booked.length === 0 ? (
            <p style={styles.muted}>No one has booked this class.</p>
          ) : (
            <ul style={styles.roster}>
              {booked.map((r) => (
                <li key={r.bookingId} style={styles.rosterRow}>
                  <span>
                    <strong>{r.memberName}</strong> <span style={styles.muted}>· ID {r.memberId}</span>
                  </span>
                  {r.attendance ? (
                    <span style={r.attendance === "Attended" ? styles.attended : styles.noShow}>{r.attendance}</span>
                  ) : (
                    <span style={styles.muted}>Booked {r.bookedAt.slice(5)}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {released.length > 0 && (
            <p style={styles.muted}>
              {released.length} cancelled reservation{released.length === 1 ? "" : "s"}:{" "}
              {released.map((r) => `${r.memberName} (${r.cancelReason || "cancelled"})`).join(", ")}
            </p>
          )}

          {detail.canEdit && detail.editable && (
            <div style={styles.actions}>
              <button type="button" onClick={() => onCancel(detail, detail.seriesFollowing)} style={styles.dangerButton}>
                Cancel class
              </button>
              <button type="button" onClick={() => onEdit(detail, detail.seriesFollowing)} style={styles.primaryButton}>
                Edit
              </button>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}

function ClassForm({ editor, branch, today, coaches, classTypes, onManageTypes, onClose, onSaved }) {
  const editing = editor.mode === "edit";
  const original = editor.gymClass;
  const [form, setForm] = useState(
    editing
      ? {
          classTypeId: String(original.classTypeId),
          coachId: String(original.coachId),
          date: original.date,
          startTime: original.startTime,
          durationMinutes: original.durationMinutes,
          capacity: original.capacity,
          room: original.room,
          description: original.description,
        }
      : { classTypeId: "", coachId: "", date: editor.date, startTime: "18:00", durationMinutes: 60, capacity: "", room: "", description: "" },
  );
  const [repeatWeeks, setRepeatWeeks] = useState(1);
  const [scope, setScope] = useState("one");
  const [fieldErrors, setFieldErrors] = useState({});
  const [conflicts, setConflicts] = useState([]);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  const update = (field, value) => setForm((f) => ({ ...f, [field]: value }));

  // A class keeps its own type in the list even if that type was archived since.
  const typeOptions =
    editing && !classTypes.some((t) => t.id === original.classTypeId)
      ? [{ id: original.classTypeId, name: original.name, maxCapacity: original.maxCapacity, archived: true }, ...classTypes]
      : classTypes;
  const selectedType = typeOptions.find((t) => String(t.id) === String(form.classTypeId));
  const maxSpots = selectedType?.maxCapacity;
  const overMax = maxSpots !== undefined && Number(form.capacity) > maxSpots;

  // A new class starts from the type's maximum and default length; switching
  // an existing class to a smaller type brings its spots down to fit.
  function chooseType(id) {
    const type = typeOptions.find((t) => String(t.id) === id);
    setForm((f) => {
      if (!type) return { ...f, classTypeId: id };
      if (!editing) return { ...f, classTypeId: id, durationMinutes: type.defaultDurationMinutes, capacity: type.maxCapacity };
      return { ...f, classTypeId: id, capacity: Math.min(Number(f.capacity), type.maxCapacity) };
    });
  }

  const start = form.startTime ? toMinutes(form.startTime) : null;
  const end = start === null ? null : start + Number(form.durationMinutes);
  const following = editing && editor.seriesFollowing > 1;

  // Coaches and studios already taken in the chosen slot, asked of the server
  // whenever the day, time or length changes - at every branch for a coach,
  // and every week of the run when repeating. They're greyed out in the
  // lists; the server checks again when the class is saved.
  const [availability, setAvailability] = useState({ coaches: {}, studios: [] });
  const [newStudio, setNewStudio] = useState(false);
  useEffect(() => {
    if (!form.date || !form.startTime || !form.durationMinutes) return undefined;
    let stale = false;
    const timer = setTimeout(() => {
      fetchAvailability({
        branch,
        date: form.date,
        startTime: form.startTime,
        durationMinutes: form.durationMinutes,
        repeatWeeks: editing ? 1 : Number(repeatWeeks),
        excludeId: editing ? original.id : undefined,
      })
        .then((body) => !stale && setAvailability(body))
        .catch(() => {});
    }, 200);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [branch, editing, original?.id, form.date, form.startTime, form.durationMinutes, repeatWeeks]);

  const busy = availability.coaches;
  const coachBusy = form.coachId ? busy[form.coachId] : null;
  const studios = availability.studios;
  const roomName = form.room.trim();
  const knownStudio = studios.find((s) => s.name.toLowerCase() === roomName.toLowerCase());
  const studioTaken = roomName ? knownStudio?.takenBy : null;
  const cannotSave =
    saving || !form.classTypeId || !form.coachId || !form.date || !form.startTime || !form.capacity || overMax ||
    Boolean(coachBusy) || Boolean(studioTaken);
  const coachOptions = editing && !coaches.some((c) => c.id === original.coachId)
    ? [{ id: original.coachId, name: `${original.coachName} (not available)`, unavailable: true }, ...coaches]
    : coaches;

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setFieldErrors({});
    setConflicts([]);
    setError(null);
    const payload = {
      ...form,
      classTypeId: Number(form.classTypeId),
      coachId: Number(form.coachId),
      durationMinutes: Number(form.durationMinutes),
      capacity: Number(form.capacity),
    };
    try {
      const result = editing
        ? await updateClass(original.id, { ...payload, scope })
        : await createClass({ ...payload, branch, repeatWeeks: Number(repeatWeeks) });
      onSaved(result.classes);
    } catch (err) {
      if (err.fieldErrors?.conflicts) setConflicts(err.fieldErrors.conflicts);
      else if (err.fieldErrors) setFieldErrors(err.fieldErrors);
      else setError(err.message);
      setSaving(false);
    }
  }

  return (
    <Modal title={editing ? `Edit ${original.name}` : `Add a class · ${formatLongDay(form.date)}`} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Class type" error={fieldErrors.classTypeId}>
          <select value={form.classTypeId} onChange={(e) => chooseType(e.target.value)} style={styles.input} autoFocus>
            <option value="">Choose a class type</option>
            {typeOptions.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} (max {t.maxCapacity}){t.archived ? " - archived" : ""}
              </option>
            ))}
          </select>
        </Field>
        {typeOptions.length === 0 && (
          <p style={styles.hint}>
            No class types at {branch} yet.{" "}
            <button type="button" onClick={onManageTypes} style={styles.linkButton}>
              Add one under Class types &amp; capacity
            </button>
          </p>
        )}

        <div style={styles.row2}>
          <Field label="Date" error={fieldErrors.date}>
            <input
              type="date"
              min={today}
              value={form.date}
              onChange={(e) => update("date", e.target.value)}
              disabled={scope === "following"}
              style={styles.input}
            />
          </Field>
          <Field label="Starts (Beirut, 24h)" error={fieldErrors.startTime}>
            <div style={styles.timePick}>
              <select
                aria-label="Start hour"
                value={form.startTime.slice(0, 2)}
                onChange={(e) => update("startTime", `${e.target.value}:${form.startTime.slice(3, 5)}`)}
                style={styles.input}
              >
                {HOURS.map((h) => (
                  <option key={h} value={h}>
                    {h}
                  </option>
                ))}
              </select>
              <span style={styles.timeColon}>:</span>
              <select
                aria-label="Start minute"
                value={form.startTime.slice(3, 5)}
                onChange={(e) => update("startTime", `${form.startTime.slice(0, 2)}:${e.target.value}`)}
                style={styles.input}
              >
                {MINUTES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </Field>
        </div>

        <div style={styles.row2}>
          <Field label="Length" error={fieldErrors.durationMinutes}>
            <select value={form.durationMinutes} onChange={(e) => update("durationMinutes", e.target.value)} style={styles.input}>
              {[...new Set([...DURATIONS, Number(form.durationMinutes)])].sort((a, b) => a - b).map((m) => (
                <option key={m} value={m}>
                  {m} min
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Spots"
            error={fieldErrors.capacity || (overMax ? `At most ${maxSpots} - the ${selectedType.name} maximum.` : null)}
          >
            <input
              type="number"
              min="1"
              max={maxSpots ?? 100}
              value={form.capacity}
              onChange={(e) => update("capacity", e.target.value)}
              style={styles.input}
            />
          </Field>
        </div>
        <p style={styles.hint}>
          {end !== null && `Ends at ${fromMinutes(end)}. `}
          {selectedType && `Up to ${maxSpots} people - the safe maximum for ${selectedType.name} at ${branch}.`}
        </p>

        <Field
          label="Coach"
          error={fieldErrors.coachId || (coachBusy ? `This coach is already teaching ${coachBusy} - pick another coach or time.` : null)}
        >
          <select value={form.coachId} onChange={(e) => update("coachId", e.target.value)} style={styles.input}>
            <option value="">Choose a coach</option>
            {coachOptions.map((c) => (
              <option key={c.id} value={c.id} disabled={c.unavailable || Boolean(busy[c.id])}>
                {c.name}
                {!c.unavailable && !c.branch ? " (any branch)" : ""}
                {busy[c.id] ? ` - busy: ${busy[c.id]}` : ""}
              </option>
            ))}
          </select>
        </Field>
        {coaches.length === 0 && <p style={styles.hint}>No coaches at {branch} yet - add one under Staff Accounts with the Coach job title.</p>}

        <Field
          label="Studio (optional)"
          error={
            fieldErrors.room ||
            (studioTaken ? `${knownStudio.name} is already taken then (${studioTaken}) - pick another studio or time.` : null)
          }
        >
          <select
            aria-label="Studio"
            value={newStudio ? "__new__" : knownStudio?.name ?? ""}
            onChange={(e) => {
              const value = e.target.value;
              setNewStudio(value === "__new__");
              update("room", value === "__new__" ? "" : value);
            }}
            style={styles.input}
          >
            <option value="">No studio</option>
            {studios.map((s) => (
              <option key={s.name} value={s.name} disabled={Boolean(s.takenBy)}>
                {s.name}
                {s.takenBy ? ` - already taken: ${s.takenBy}` : ""}
              </option>
            ))}
            <option value="__new__">+ New studio...</option>
          </select>
          {newStudio && (
            <input
              value={form.room}
              onChange={(e) => update("room", e.target.value)}
              placeholder="Name of the new studio, e.g. Studio C"
              aria-label="New studio name"
              style={{ ...styles.input, marginTop: 8 }}
              autoFocus
            />
          )}
        </Field>

        <Field label="Description (optional)" error={fieldErrors.description}>
          <textarea
            value={form.description}
            onChange={(e) => update("description", e.target.value)}
            rows={2}
            style={{ ...styles.input, resize: "vertical" }}
          />
        </Field>

        {!editing && (
          <Field label="Repeat" error={fieldErrors.repeatWeeks}>
            <select value={repeatWeeks} onChange={(e) => setRepeatWeeks(e.target.value)} style={styles.input}>
              <option value={1}>Just this date</option>
              {[2, 3, 4, 6, 8, 10, 12].map((n) => (
                <option key={n} value={n}>
                  Every week for {n} weeks
                </option>
              ))}
            </select>
          </Field>
        )}

        {following && (
          <fieldset style={styles.scopeBox}>
            <legend style={styles.fieldLabel}>Apply to</legend>
            <label style={styles.radio}>
              <input type="radio" checked={scope === "one"} onChange={() => setScope("one")} /> Only this class
            </label>
            <label style={styles.radio}>
              <input
                type="radio"
                checked={scope === "following"}
                onChange={() => {
                  setScope("following");
                  update("date", original.date);
                }}
              />{" "}
              This and the following {editor.seriesFollowing - 1} class{editor.seriesFollowing > 2 ? "es" : ""} in the series
            </label>
          </fieldset>
        )}

        {conflicts.length > 0 && (
          <div style={styles.errorBox}>
            <strong>This clashes with the schedule:</strong>
            <ul style={styles.conflictList}>
              {conflicts.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {error && <div style={styles.errorBox}>{error}</div>}

        <div style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.secondaryButton}>
            Cancel
          </button>
          <button
            type="submit"
            disabled={cannotSave}
            style={cannotSave ? { ...styles.primaryButton, ...styles.buttonDisabled } : styles.primaryButton}
          >
            {saving ? "Saving..." : editing ? "Save changes" : "Add class"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function CancelDialog({ target, onClose, onCancelled }) {
  const { gymClass, seriesFollowing } = target;
  const [reason, setReason] = useState("");
  const [scope, setScope] = useState("one");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      onCancelled(await cancelClass(gymClass.id, { reason, scope }));
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  return (
    <Modal title={`Cancel ${gymClass.name}?`} onClose={onClose}>
      <form onSubmit={submit}>
        <p style={styles.modalText}>
          {formatLongDay(gymClass.date)} · {gymClass.startTime}–{gymClass.endTime} with {gymClass.coachName}. It stays on the
          calendar marked as cancelled
          {gymClass.booked > 0 ? `, and the ${gymClass.booked} booked member${gymClass.booked === 1 ? " loses their" : "s lose their"} spot.` : "."}
        </p>
        <Field label="Reason (optional)">
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Coach is ill" style={styles.input} />
        </Field>
        {seriesFollowing > 1 && (
          <fieldset style={styles.scopeBox}>
            <legend style={styles.fieldLabel}>Cancel</legend>
            <label style={styles.radio}>
              <input type="radio" checked={scope === "one"} onChange={() => setScope("one")} /> Only this class
            </label>
            <label style={styles.radio}>
              <input type="radio" checked={scope === "following"} onChange={() => setScope("following")} /> This and the
              following {seriesFollowing - 1} in the series
            </label>
          </fieldset>
        )}
        {error && <div style={styles.errorBox}>{error}</div>}
        <div style={styles.actions}>
          <button type="button" onClick={onClose} style={styles.secondaryButton}>
            Keep class
          </button>
          <button type="submit" disabled={saving} style={styles.dangerButton}>
            {saving ? "Cancelling..." : "Cancel class"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, wide, children }) {
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div
        style={{ ...styles.modal, maxWidth: wide ? 560 : 460 }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={title}
      >
        <div style={styles.modalHeader}>
          <h2 style={styles.modalTitle}>{title}</h2>
          <button type="button" onClick={onClose} style={styles.closeButton} aria-label="Close">
            &times;
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({ label, error, children }) {
  const message = Array.isArray(error) ? error[0] : error;
  return (
    <div style={styles.field}>
      <label style={styles.fieldLabel}>{label}</label>
      {children}
      {message && <div style={styles.fieldError}>{message}</div>}
    </div>
  );
}

function Info({ label, value }) {
  return (
    <div style={styles.info}>
      <span style={styles.infoLabel}>{label}</span>
      <span style={styles.infoValue}>{value}</span>
    </div>
  );
}

const styles = {
  page: {
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    maxWidth: 1240,
    margin: "0 auto",
    padding: "32px 20px",
    color: "#1a1a1a",
  },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16, flexWrap: "wrap", marginBottom: 16 },
  title: { fontSize: 22, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: "#666", marginTop: 4 },
  muted: { fontSize: 13, color: "#888" },
  branchPicker: { display: "flex", alignItems: "center", gap: 8 },
  branchChip: {
    padding: "8px 14px",
    borderRadius: 999,
    background: "#eef2fa",
    color: "#124096",
    fontSize: 14,
    fontWeight: 600,
  },
  select: { padding: "8px 10px", fontSize: 14, border: "1px solid #d0d0d5", borderRadius: 8, background: "#fff" },
  viewBar: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 14 },
  viewSwitch: { flex: "0 1 440px", minWidth: 0 },
  clock: {
    display: "inline-flex",
    alignItems: "baseline",
    gap: 8,
    padding: "6px 12px",
    borderRadius: 10,
    background: "#fff",
    border: "1px solid #e4e4e8",
  },
  clockLabel: { fontSize: 12, fontWeight: 600, color: "#666" },
  clockTime: { fontSize: 20, fontWeight: 800, fontVariantNumeric: "tabular-nums", color: "#124096" },
  clockDay: { fontSize: 12, color: "#666" },
  timePick: { display: "flex", alignItems: "center", gap: 4 },
  timeColon: { fontWeight: 700 },
  linkButton: { border: "none", background: "none", padding: 0, color: "#124096", fontSize: 13, fontWeight: 600, cursor: "pointer" },
  toolbar: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 10 },
  weekNav: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
  navButton: {
    width: 36,
    height: 36,
    fontSize: 20,
    lineHeight: 1,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
  todayButton: {
    height: 36,
    padding: "0 14px",
    fontSize: 14,
    fontWeight: 600,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
  },
  weekLabel: { fontSize: 17, fontWeight: 700, marginLeft: 6 },
  jump: { display: "flex", alignItems: "center", gap: 8 },
  legend: { display: "flex", gap: 16, flexWrap: "wrap", fontSize: 12, color: "#555", marginBottom: 12 },
  legendItem: { display: "inline-flex", alignItems: "center", gap: 6 },
  swatch: { width: 14, height: 14, borderRadius: 4, display: "inline-block" },
  swatchPast: { background: "#ececf0", border: "1px solid #d6d6dc" },
  swatchToday: { background: "#eef3fc", border: "2px solid #124096" },
  swatchUpcoming: { background: "#fff", border: "1px solid #d0d0d5" },
  grid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 10, alignItems: "start" },
  day: { borderRadius: 12, padding: 10, minHeight: 160, display: "flex", flexDirection: "column", gap: 8, boxSizing: "border-box" },
  dayPast: { background: "#ececf0", border: "1px solid #dcdce2" },
  dayToday: { background: "#eef3fc", border: "2px solid #124096" },
  dayUpcoming: { background: "#fff", border: "1px solid #e4e4e8" },
  dayHeader: { display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", minHeight: 24 },
  dayName: { fontSize: 14, fontWeight: 700 },
  todayBadge: {
    padding: "2px 8px",
    borderRadius: 999,
    background: "#124096",
    color: "#fff",
    fontSize: 11,
    fontWeight: 700,
  },
  pastBadge: {
    padding: "2px 8px",
    borderRadius: 999,
    background: "#dcdce2",
    color: "#555",
    fontSize: 11,
    fontWeight: 600,
  },
  emptyDay: { fontSize: 12, color: "#999", padding: "8px 2px" },
  card: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: 2,
    width: "100%",
    padding: "8px 10px",
    textAlign: "left",
    border: "1px solid #e4e4e8",
    borderLeft: "4px solid",
    borderRadius: 8,
    background: "#fff",
    cursor: "pointer",
    fontFamily: "inherit",
    color: "inherit",
    boxSizing: "border-box",
  },
  cardMuted: { background: "#f7f7f9", color: "#77777f" },
  ptCard: { borderStyle: "dashed", borderLeftStyle: "solid", background: "#f3faf5" },
  cardTime: { fontSize: 12, fontWeight: 700 },
  cardName: { fontSize: 14, fontWeight: 700, lineHeight: 1.25 },
  cardMeta: { fontSize: 12, color: "inherit", opacity: 0.85 },
  cardFooter: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 4,
    width: "100%",
    marginTop: 2,
  },
  cardSpots: { fontSize: 11, color: "inherit", opacity: 0.85, whiteSpace: "nowrap" },
  stateTag: { fontSize: 10, fontWeight: 700, padding: "1px 6px", borderRadius: 4, whiteSpace: "nowrap" },
  tagLive: { background: "#e3f5e8", color: "#0f6e2b" },
  tagDone: { background: "#e4e4e8", color: "#555" },
  tagCancelled: { background: "#fdeceb", color: "#b3261e" },
  tagFull: { background: "#fff1d6", color: "#8a5300" },
  coachWarning: { fontSize: 11, fontWeight: 700, color: "#a15c00", marginTop: 2 },
  addButton: {
    marginTop: "auto",
    padding: "8px 10px",
    fontSize: 13,
    fontWeight: 600,
    border: "1px dashed #9aa6c4",
    borderRadius: 8,
    background: "transparent",
    color: "#124096",
    cursor: "pointer",
  },
  successBox: { background: "#e3f5e8", color: "#0f6e2b", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  errorBox: { background: "#fdeceb", color: "#b3261e", padding: "10px 14px", borderRadius: 8, fontSize: 14, marginBottom: 12 },
  lockBox: { background: "#ececf0", color: "#555", padding: "10px 14px", borderRadius: 8, fontSize: 14, margin: "12px 0" },
  conflictList: { margin: "6px 0 0", paddingLeft: 18 },
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.4)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 20,
    zIndex: 1000,
  },
  modal: {
    background: "#fff",
    borderRadius: 12,
    padding: 24,
    width: "100%",
    maxHeight: "90vh",
    overflowY: "auto",
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    color: "#1a1a1a",
    boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
    boxSizing: "border-box",
  },
  modalHeader: { display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: 14 },
  modalTitle: { fontSize: 18, fontWeight: 700, margin: 0 },
  modalText: { fontSize: 14, color: "#555", lineHeight: 1.5, margin: "0 0 14px" },
  closeButton: { border: "none", background: "transparent", fontSize: 22, lineHeight: 1, cursor: "pointer", color: "#888" },
  detailGrid: { display: "grid", gap: 8 },
  info: { display: "flex", gap: 12, fontSize: 14 },
  infoLabel: { width: 80, flexShrink: 0, color: "#666" },
  infoValue: { fontWeight: 600 },
  rosterTitle: { fontSize: 15, fontWeight: 700, margin: "16px 0 8px" },
  roster: { listStyle: "none", margin: 0, padding: 0, border: "1px solid #e4e4e8", borderRadius: 8 },
  rosterRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 10,
    padding: "8px 12px",
    borderBottom: "1px solid #f0f0f3",
    fontSize: 14,
  },
  attended: { fontSize: 12, fontWeight: 700, color: "#0f6e2b", background: "#e3f5e8", padding: "2px 8px", borderRadius: 4 },
  noShow: { fontSize: 12, fontWeight: 700, color: "#b3261e", background: "#fdeceb", padding: "2px 8px", borderRadius: 4 },
  field: { marginBottom: 12, flex: 1, minWidth: 0 },
  fieldLabel: { display: "block", fontSize: 13, fontWeight: 600, marginBottom: 6, color: "#444" },
  fieldError: { color: "#b3261e", fontSize: 12, marginTop: 4 },
  row2: { display: "flex", gap: 10 },
  input: {
    width: "100%",
    padding: "9px 11px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    outline: "none",
    background: "#fff",
    boxSizing: "border-box",
    fontFamily: "inherit",
  },
  hint: { fontSize: 13, color: "#555", margin: "-4px 0 12px" },
  scopeBox: { border: "1px solid #e4e4e8", borderRadius: 8, padding: "8px 12px", margin: "0 0 12px" },
  radio: { display: "flex", alignItems: "center", gap: 6, fontSize: 14, padding: "4px 0" },
  actions: { display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 18, flexWrap: "wrap" },
  primaryButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.blue,
    fontWeight: 600,
    cursor: "pointer",
  },
  buttonDisabled: { background: "#c9cdd3", color: "#fff", cursor: "not-allowed" },
  secondaryButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "1px solid #d0d0d5",
    borderRadius: 8,
    background: "#f5f5f7",
    cursor: "pointer",
  },
  dangerButton: {
    padding: "10px 16px",
    fontSize: 14,
    border: "none",
    borderRadius: 8,
    ...BUTTON_COLORS.red,
    fontWeight: 600,
    cursor: "pointer",
  },
};
