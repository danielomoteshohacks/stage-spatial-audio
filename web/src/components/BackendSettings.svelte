<script lang="ts">
  import type { Diagnosis } from "../lib/api";
  import { BUILD_DEFAULT_BACKEND, normaliseBackendUrl } from "../lib/settings";
  import Icon from "./Icon.svelte";

  let {
    url,
    status,
    diagnosis,
    onsave,
    oncheck,
  }: {
    url: string;
    status: "checking" | "online" | "offline";
    diagnosis: Diagnosis | null;
    onsave: (url: string) => void;
    oncheck: () => void;
  } = $props();

  let dialog: HTMLDialogElement | undefined = $state();
  let draft = $state("");
  let error = $state("");

  export function open() {
    draft = url;
    error = "";
    dialog?.showModal();
  }

  function save(event: SubmitEvent) {
    event.preventDefault();
    try {
      onsave(normaliseBackendUrl(draft));
      dialog?.close();
    } catch (e) {
      error = (e as Error).message;
    }
  }
</script>

<dialog bind:this={dialog} aria-labelledby="settings-title" class="sheet">
  <form onsubmit={save}>
    <header>
      <h2 id="settings-title" class="section-title">Backend</h2>
      <button type="button" class="btn btn-ghost btn-sm" onclick={() => dialog?.close()} aria-label="Close settings">
        <Icon name="x" />
      </button>
    </header>
    <p class="muted">
      Where tracks are processed: your laptop running <code>python space/app.py</code>, or your Hugging Face Space.
    </p>
    <label class="field-label" for="backend-url">Backend address</label>
    <input
      id="backend-url"
      class="input mono"
      type="url"
      inputmode="url"
      autocomplete="off"
      spellcheck="false"
      bind:value={draft}
      aria-describedby="backend-help"
      aria-invalid={error ? "true" : undefined}
    />
    <p id="backend-help" class="faint">
      Laptop on this device: <code>http://127.0.0.1:7860</code>. Laptop on your Wi-Fi: <code>http://&lt;laptop IP&gt;:7860</code>.
      Space: <code>https://&lt;user&gt;-&lt;space&gt;.hf.space</code>. Saved in this browser only.
    </p>
    {#if error}<p class="err" role="alert">{error}</p>{/if}
    <div class="row">
      <button type="button" class="btn btn-ghost btn-sm" onclick={() => (draft = BUILD_DEFAULT_BACKEND)}>
        Use default
      </button>
      <span class="spacer"></span>
      <button type="submit" class="btn btn-primary">Save and check</button>
    </div>
    <div class="state" aria-live="polite">
      {#if status === "checking"}
        <p class="faint">Checking {url} ...</p>
      {:else if status === "online"}
        <p class="ok"><Icon name="check" size={16} /> Connected to {url}</p>
      {:else if diagnosis}
        <p><strong>{diagnosis.title}</strong></p>
        <p class="faint">{diagnosis.detail}</p>
        <ol>
          {#each diagnosis.fixes as fix (fix)}<li>{fix}</li>{/each}
        </ol>
        <button type="button" class="btn btn-sm" onclick={oncheck}><Icon name="refresh" size={16} /> Check again</button>
      {/if}
    </div>
  </form>
</dialog>

<style>
  .sheet {
    width: min(560px, calc(100vw - 2 * var(--gutter)));
    max-height: calc(100dvh - 32px);
    margin: auto;
    padding: 0;
    border: 1px solid var(--line-strong);
    border-radius: var(--radius);
    background: var(--surface);
    color: var(--text);
  }
  .sheet::backdrop {
    background: rgba(0, 0, 0, 0.7);
    backdrop-filter: blur(4px);
  }
  form {
    display: grid;
    gap: 14px;
    padding: 20px;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .spacer {
    flex: 1;
  }
  .err {
    color: var(--danger);
    font-size: 14px;
  }
  .ok {
    display: flex;
    gap: 6px;
    align-items: center;
    color: var(--ok);
  }
  .state {
    display: grid;
    gap: 8px;
    padding-top: 6px;
    border-top: 1px solid var(--line);
  }
  ol {
    margin: 0;
    padding-left: 20px;
    color: var(--text-2);
    font-size: 14px;
    display: grid;
    gap: 6px;
    word-break: break-word;
  }
</style>
