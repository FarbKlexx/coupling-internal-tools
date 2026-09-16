import { computed, ref, shallowRef, watch } from "vue";
import axios from "axios";
import {
  createEntry,
  fetchBoard,
  updateContact,
  updateEntry,
  type BuildReadiness,
  type MailBoard,
  type MailState,
  type MailUpdate,
  type MailView,
  type ManualEntry,
} from "@/api/mail_followup.api";

/**
 * Die Versandliste.
 *
 * Kein Store, wie bei der Telefonakquise: der Stand lebt in dieser einen View,
 * und jeder schreibende Aufruf liefert ihn vollständig zurück – es gibt also
 * keine optimistische Buchführung, die auseinanderlaufen könnte.
 *
 * Anders als der Arbeitsstand der Telefonakquise wird hier **nicht gepollt**.
 * Diese Liste ändert sich nicht von selbst: es gibt keine Frist, die im
 * Minutentakt etwas fällig macht, und die 10 bzw. 30 Tage sind am nächsten Tag
 * noch rechtzeitig zu sehen. Ein Hintergrundabruf würde nur die Zeile umsortieren,
 * an der gerade jemand arbeitet.
 */
export function useMailFollowup() {
  const board = shallowRef<MailBoard | null>(null);
  // Startet auf `true`: `onMounted` feuert nach dem ersten Rendern, und mit
  // `false` zeigte die Seite in diesem einen Tick „keine Zusagen".
  const isLoading = ref(true);
  const isSaving = ref(false);
  const errorMessage = ref<string | null>(null);

  /** Die aktuelle Sicht – sie reist mit jedem Schreibzugriff mit. */
  const query = ref("");
  const stateFilter = ref<MailState | null>(null);
  /** Zweiter Filter, unabhängig vom ersten. `null` heißt „alle". */
  const readinessFilter = ref<BuildReadiness | null>(null);
  /** Dritter Filter: der Umfang. `null` heißt „alle", `true` nur die großen.
   *  `false` wäre „nur die erwarteten" – die Oberfläche schaltet aber nur
   *  zwischen `null` und `true`, weil „ohne Marker" keine Frage ist, die
   *  jemand stellt. */
  const oversizedFilter = ref<boolean | null>(null);
  const offset = ref(0);

  const counters = computed(() => board.value?.counters ?? null);
  const entries = computed(() => board.value?.entries ?? []);
  const actions = computed(() => board.value?.actions ?? []);
  const readinessOptions = computed(() => board.value?.readiness_options ?? []);
  const scopeMarker = computed(() => board.value?.scope_marker ?? null);
  const timeoutDays = computed(() => board.value?.timeout_days ?? 30);
  const followupDays = computed(() => board.value?.followup_days ?? 10);

  function view(): MailView {
    return {
      q: query.value,
      state: stateFilter.value,
      readiness: readinessFilter.value,
      oversized: oversizedFilter.value,
      offset: offset.value,
    };
  }

  function readDetail(error: unknown, fallback: string): string {
    if (axios.isAxiosError(error)) {
      const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
      if (typeof detail === "string") return detail;
    }
    return fallback;
  }

  async function load(options: { keepError?: boolean } = {}) {
    isLoading.value = true;
    if (!options.keepError) errorMessage.value = null;
    try {
      board.value = await fetchBoard(view());
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, "Die Versandliste konnte nicht geladen werden.");
    } finally {
      isLoading.value = false;
    }
  }

  // Suche und Filter laden neu und fangen dabei vorne an: eine Seite 3, die es
  // nach dem Filtern nicht mehr gibt, wäre eine leere Liste ohne Erklärung.
  let searchTimer: ReturnType<typeof setTimeout> | null = null;

  watch(query, () => {
    if (searchTimer !== null) clearTimeout(searchTimer);
    // 300 ms wie bei der Blacklist: kurz genug, dass es sich wie Tippen
    // anfühlt, lang genug für einen Request statt zehn.
    searchTimer = setTimeout(() => {
      offset.value = 0;
      void load();
    }, 300);
  });

  /**
   * Einen Reiter wählen. `null` ist „Alle".
   *
   * Setzt, statt zu wechseln: die Reiter zeigen, welcher gilt, und ein Klick
   * auf den aktiven soll ihn nicht abwählen (das wäre bei einem Reiter eine
   * Überraschung). Derselbe Wert lädt deshalb auch nicht neu.
   */
  function filterBy(state: MailState | null) {
    if (stateFilter.value === state) return;

    stateFilter.value = state;
    offset.value = 0;
    void load();
  }

  /**
   * Die Bau-Einschätzung filtern. `null` ist „alle".
   *
   * Anders als der Reiter ein Umschalter: derselbe Wert nochmal hebt den
   * Filter auf. Die Marker sind eine Auswahl neben der Reiterzeile, und dort
   * ist „nochmal klicken" der erwartete Rückweg – ein Reiter dagegen zeigt,
   * welcher gerade gilt, und darf sich nicht ins Nichts abwählen lassen.
   */
  function filterByReadiness(readiness: BuildReadiness | null) {
    readinessFilter.value = readinessFilter.value === readiness ? null : readiness;
    offset.value = 0;
    void load();
  }

  /**
   * Den Umfang filtern. Umschalter wie die Bau-Einschätzung.
   *
   * Nur zwischen „alle" und „nur die großen": „nur die, die niemand als groß
   * markiert hat" ist keine Frage, die jemand stellt – das Fehlen des Markers
   * ist keine Aussage. Das Backend kann es trotzdem (`oversized=false`), weil
   * der Filter dort eine URL ist und keine Oberfläche.
   */
  function filterByScope() {
    oversizedFilter.value = oversizedFilter.value ? null : true;
    offset.value = 0;
    void load();
  }

  function goToPage(next: number) {
    if (!board.value) return;
    if (next < 0 || next >= board.value.matched) return;

    offset.value = next;
    void load();
  }

  /**
   * Einen Zustand setzen, eine Anmerkung schreiben oder einen Marker setzen.
   *
   * Die Sicht reist mit, damit die Antwort dieselbe Seite zeigt wie vorher –
   * sonst spränge die Liste nach jedem Klick zurück an den Anfang.
   */
  async function save(contactId: string, update: MailUpdate): Promise<boolean> {
    isSaving.value = true;
    errorMessage.value = null;
    try {
      board.value = await updateEntry(contactId, update, view());
      return true;
    } catch (e) {
      console.error(e);
      errorMessage.value = readDetail(e, "Die Änderung wurde nicht gespeichert.");
      // Die Liste kann veraltet sein – etwa wenn die Zusage inzwischen
      // richtiggestellt wurde. Dann ist der neue Stand die Antwort auf den
      // Fehler, aber die Meldung dazu muss stehen bleiben.
      await load({ keepError: true });
      return false;
    } finally {
      isSaving.value = false;
    }
  }

  /**
   * Die Meldung zu einer schon bekannten Nummer (409), oder `null`.
   *
   * Getrennt von `formError`, weil die Oberfläche darauf anders antwortet:
   * ein Befund bekommt den Knopf „trotzdem anlegen", ein Tippfehler nicht.
   */
  const conflict = ref<string | null>(null);
  /** Fehler des Formulars – sie gehören in den Dialog, nicht über die Liste. */
  const formError = ref<string | null>(null);

  /**
   * Einen von Hand erfassten Betrieb anlegen oder ändern.
   *
   * Eine Funktion für beides: es ist dasselbe Formular, und der einzige
   * Unterschied ist, ob es den Kontakt schon gibt. Liefert `true`, wenn
   * gespeichert wurde – dann schließt der Dialog.
   *
   * Nach dem **Anlegen** fallen Suche und Filter weg und die Liste springt auf
   * Seite eins: der neue Betrieb steht auf „offen", und wer gerade auf
   * „Verschickt" gefiltert hatte, sähe sonst nach dem Speichern nichts und
   * hielte es für fehlgeschlagen.
   */
  async function submitContact(entry: ManualEntry, contactId: string | null): Promise<boolean> {
    isSaving.value = true;
    formError.value = null;
    conflict.value = null;

    try {
      board.value = contactId
        ? await updateContact(contactId, entry, view())
        : await createEntry(entry, view());
    } catch (e) {
      console.error(e);
      if (axios.isAxiosError(e) && e.response?.status === 409) {
        conflict.value = readDetail(e, "Diese Nummer ist schon bekannt.");
      } else {
        formError.value = readDetail(e, "Der Betrieb wurde nicht gespeichert.");
      }
      return false;
    } finally {
      isSaving.value = false;
    }

    if (!contactId) {
      query.value = "";
      stateFilter.value = null;
      readinessFilter.value = null;
      oversizedFilter.value = null;
      offset.value = 0;
      await load();
    }

    return true;
  }

  return {
    board,
    counters,
    entries,
    actions,
    timeoutDays,
    followupDays,
    readinessOptions,
    scopeMarker,
    query,
    stateFilter,
    readinessFilter,
    oversizedFilter,
    isLoading,
    isSaving,
    errorMessage,
    conflict,
    formError,

    load,
    submitContact,
    filterBy,
    filterByReadiness,
    filterByScope,
    goToPage,
    save,
  };
}
