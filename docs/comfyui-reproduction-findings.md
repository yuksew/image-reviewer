# ComfyUI 0.39.2 再現・workflow オープン経路 調査結果

対象: `C:\ai\ComfyUI_windows_portable\ComfyUI`（ComfyUI 0.39.2 / comfyui-frontend-package 1.53.10 / python_embeded 3.13.14 / PyTorch 2.13.0+cu130 / RTX 3060）
稼働: `http://127.0.0.1:8188`（`--windows-standalone-build --port 8188`）
調査: 読み取りのみ。ファイル変更・生成実行なし。

フロントエンドのバンドル実体（`ComfyUI\web\assets\` は**存在しない**）:
`C:\ai\ComfyUI_windows_portable\python_embeded\Lib\site-packages\comfyui_frontend_package\static\assets\`
同ディレクトリの `.js.map` に元の TypeScript ソース（`sourcesContent`）が入っており、以下の引用はそこから取得。

---

## 1. API 形式 prompt JSON をフロントエンドが読めるか

**結論: サポートされている。** ドラッグ&ドロップでも「Open」ボタンのファイル選択でも読める。

判定は拡張子/MIME で分岐し、`.json` は `src/scripts/metadata/json.ts` の `getDataFromJSON` に落ちる。

`src/scripts/metadata/json.ts`（全文 41 行、抜粋）:

```ts
export function getDataFromJSON(file: File): Promise<Record<string, object> | undefined> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = async () => {
      try {
        if (typeof reader.result !== 'string') { resolve(undefined); return }
        const jsonContent = parseJsonWithNonFinite<Record<string, unknown>>(reader.result)
        if (jsonContent?.templates) { resolve({ templates: jsonContent.templates as object }); return }
        if (isApiJson(jsonContent)) { resolve({ prompt: jsonContent }); return }
        resolve({ workflow: jsonContent })
      } catch { resolve(undefined) }
    }
    ...
  })
}

function isApiJson(data: unknown) {
  return isObject(data) && Object.values(data).every((v) => v.class_type)
}
```

`src/scripts/metadata/parser.ts:69-71`:

```ts
  if (file.type === 'application/json' || file.name?.endsWith('.json')) {
    return getDataFromJSON(file)
  }
```

`src/scripts/app.ts:2005-2149`（`handleFile`。UI 形式を優先し、無ければ API 形式を試す）:

```ts
    // Check workflow first - it should take priority over parameters
    // when both are present (e.g., in ComfyUI-generated PNGs)
    if (workflow) {
      ...
      await this.loadGraphData(workflowObj, true, true, fileName, { openSource, deferWarnings: options?.deferWarnings })
      return
    }
    ...
    if (prompt) {
      try {
        const promptObj = typeof prompt === 'string'
          ? parseJsonWithNonFinite<ComfyApiWorkflow>(prompt) : prompt
        if (this.isApiJson(promptObj)) {
          await this.loadApiJson(promptObj, fileName, { deferWarnings: options?.deferWarnings })
          return
        }
      } catch (err) { console.error('Failed to parse prompt:', err) }
    }
```

`src/scripts/app.ts:2255-2271`（API 形式の判定条件。**全エントリ**が条件を満たす必要がある `every`）:

```ts
  // @deprecated
  isApiJson(data: unknown): data is ComfyApiWorkflow {
    if (!_.isObject(data) || Array.isArray(data)) return false
    if (Object.keys(data).length === 0) return false
    return Object.values(data).every((node) => {
      if (!node || typeof node !== 'object' || Array.isArray(node)) return false
      const { class_type: classType, inputs } = node as Record<string, unknown>
      const inputsIsRecord = _.isObject(inputs) && !Array.isArray(inputs)
      return typeof classType === 'string' && inputsIsRecord
    })
  }
```

`src/scripts/app.ts:2273-2430` に `loadApiJson()` 本体があり、`LiteGraph.createNode(data.class_type)` でノードを再生成 → `inputs` の配列はリンク、非配列は `node.widgets.find(w => w.name === input)` に値をセット → `app.rootGraph.arrange()` → `afterLoadNewGraph`。
つまり **API 形式 → UI 形式への変換は完全に実装済み**。

入口（2 つ）:

- **D&D**: `src/scripts/app.ts:704` `useEventListener(document, 'drop', async (event: DragEvent) => {` → `755` / `759` `await this.handleFile(file, 'file_drop', handleFileOptions)`
- **Open ボタン**: `src/composables/useCoreCommands.ts:162-169` の `Comfy.OpenWorkflow` → `app.ui.loadFile()` → `src/scripts/ui.ts:415-436`:

```ts
    const fileInput = $el('input', {
      id: 'comfy-file-input',
      type: 'file',
      accept: WORKFLOW_ACCEPT_STRING,
      style: { display: 'none' },
      parent: document.body,
      onchange: async () => {
        const file = fileInput.files?.[0]
        if (file) {
          try { await app.handleFile(file, 'file_button') }
          catch (error) { console.error('Failed to load file:', error); app.showErrorOnFileLoad(file) }
          finally { fileInput.value = '' }
        }
      }
    })
    this.loadFile = () => fileInput.click()
```

`WORKFLOW_ACCEPT_STRING`（`src/platform/workflow/core/types/formats.ts:69-72`）は `DATA_WORKFLOW_FORMATS.extensions = ['.json', '.latent', '.safetensors']` を含む（`formats.ts:40-42`）。

エラーになる条件:

- 空オブジェクト `{}`、配列、トップレベルが非オブジェクト
- 値の中に `class_type` が string でない、または `inputs` が object でないものが **1 つでもある**と `every` が false → `parameters` フォールバック → `showErrorOnFileLoad`
- カスタムノード未インストールでも **読み込み自体は成功**し、missing node プレースホルダ（`node.has_errors = true`）になる（`app.ts:2313-2356`）

PNG の `prompt` チャンクも同じ経路（`workflow` チャンクがあればそちらが優先）。

*未検証*: 実ブラウザでの目視確認はしていない（コード上の確認のみ）。

---

## 2. URL から特定 workflow を開く方法

- `?workflow=` … **存在しない**。
- `?template=<id>` … **存在する**（このバージョンで実装済み）。ユーザーの指摘「0 hits」は、minify 後のバンドルを文字列検索したため。ソースマップ上には明確に存在する。
- `?share=<id>` … 存在するが Comfy のシェア（クラウド）機能前提。ローカルでの動作は*未検証*。

`src/platform/navigation/preservedQueryNamespaces.ts`（全文）:

```ts
export const PRESERVED_QUERY_NAMESPACES = {
  TEMPLATE: 'template',
  INVITE: 'invite',
  SHARE: 'share',
  SHARE_AUTH: 'share_auth',
  CREATE_WORKSPACE: 'create_workspace',
  OAUTH: 'oauth',
  PRICING: 'pricing',
  TOPUP: 'topup',
  SETTINGS: 'settings',
  DESKTOP_LOGIN: 'desktop_login'
} as const
```

→ **`WORKFLOW` 名前空間は無い。**

`src/platform/workflow/persistence/composables/useWorkflowPersistenceV2.ts:226-237, 286-293`:

```ts
  const hasPreservedIntent = (namespace: string, key: string) => {
    if (typeof route.query[key] === 'string') return true
    hydratePreservedQuery(namespace)
    const merged = mergePreservedQueryIntoQuery(namespace, route.query)
    return typeof merged?.[key] === 'string'
  }
  const hasTemplateUrlIntent = () => hasPreservedIntent(TEMPLATE_NAMESPACE, 'template')
  ...
  const loadTemplateFromUrlIfPresent = async () => {
    const query = await ensureTemplateQueryFromIntent()
    const hasTemplateUrl = query.template && typeof query.template === 'string'
    return hasTemplateUrl ? await templateUrlLoader.loadTemplateFromUrl() : undefined
  }
```

`src/platform/workflow/templates/composables/useTemplateUrlLoader.ts:13-24, 68-115`:

```ts
/**
 * Supports URLs like:
 * - /?template=flux_simple (loads with default source)
 * - /?template=flux_simple&source=custom (loads from custom source)
 * - /?template=flux_simple&mode=linear (loads template in linear mode)
 *
 * Input validation:
 * - Template, source, and mode parameters must match: ^[a-zA-Z0-9_-]+$
 */
...
    const templateParam = route.query.template
    if (!templateParam || typeof templateParam !== 'string') return
    if (!isValidParameter(templateParam)) { console.warn(...); return }
    const sourceParam = (route.query.source as string | undefined) || 'default'
...
      const success = await templateWorkflows.loadWorkflowTemplate(templateParam, sourceParam)
```

`src/platform/workflow/templates/composables/useTemplateWorkflows.ts:156-165` が実体:

```ts
  const fetchTemplateJson = async (id: string, sourceModule: string) => {
    if (sourceModule === 'default') {
      return fetch(api.fileURL(`/templates/${id}.json`)).then((r) => r.json())
    } else {
      return fetch(api.apiURL(`/workflow_templates/${sourceModule}/${id}.json`)).then((r) => r.json())
    }
  }
```

→ `?template=` で開けるのは **同梱テンプレート** (`/templates/<id>.json`) または **カスタムノードの example_workflows** (`/api/workflow_templates/<module>/<id>.json`、`app/custom_node_manager.py:122-138` が静的配信) のみ。
**`user/default/workflows/` 配下の任意ファイルを URL で開く手段は無い。**

さらに `/history/first` の `route.query` を消す処理（`cleanupUrlParams` が `router.replace` で `template`/`source`/`mode` を削除）がある。

`/api/userdata` 経由の自動 fetch:

- フロントエンドの通常フローはサイドバー（`workflowStore`）が `api.listUserDataFullInfo('workflows')` → `api.getUserData(path)` → `workflow.load()` → `app.loadGraphData()`。**URL パラメータ起点の自動 fetch は無い**（`src/scripts/api.ts:1427-1503` に `getUserData`/`storeUserData`/`listUserDataFullInfo` はあるが、`route.query` からは呼ばれない）。
- `location.hash` を使うディープリンク処理は ComfyUI 側ソースに**存在しない**（バンドル内の `location.hash` ヒットは vue-router / @vueuse / @datadog のみ）。
- `URLSearchParams` / `searchParams` のヒットは全て `/view?filename=...`、`/upload`、テレメトリ、外部リンク等であり、workflow ディープリンクではない。
- `window.location.search` を読むのは `src/utils/sessionFeatureFlagOverride.ts:138`（機能フラグ上書き）と lib0(yjs) のみ。
- 参考: `GET /api/userdata/{file}` は `Content-Disposition: attachment`（`X-Content-Type-Options: nosniff`）を付けて返す（`app/user_manager.py:358-362`）ため、URL を直接ブラウザで開いてもアプリ内ロードはされない。
- `vue-router` はバンドルに含まれるが、ルート定義に workflow 用の path パラメータは無い（`route.query` のみ）。

---

## 3. HTTP API で `user/default/workflows/` に書き込めるか

**書き込みルートは存在する。**

### 実測: 一覧（読み取りのみ）

```
GET /api/userdata?dir=workflows&recurse=true&split=false&full_info=true
```

`/api` 無しの `/userdata?...` でも同じレスポンス（後述の router プレフィックス）。20 件、例:

```json
[{"path":"dog.json","size":17479,"modified":1791904447119,"created":1791904447119},
 {"path":"ja2en_4b_int8.json","size":31844,"modified":1791856593500,"created":1791856593499},
 {"path":"NoctQ_V4.json","size":5711,"modified":1791500060928,"created":1791500060926},
 {"path":"sample2 (Copy).json","size":8642,"modified":1790539126190,"created":1790539126190}]
```

`modified`/`created` は **ミリ秒**（`app/user_manager.py:27-33` の `int(os.path.getmtime(path) * 1000)`）。

### 書き込みルート定義（`app/user_manager.py:364-425`）

```python
        @routes.post("/userdata/{file}")
        async def post_userdata(request):
            """
            Upload or update a user data file.
            Query Parameters:
            - overwrite (optional): If "false", prevents overwriting existing files. Defaults to "true".
            - full_info (optional): If "true", returns detailed file information (path, size, modified time).
            Path Parameters:
            - file: The target file path (URL encoded if necessary).
            The request body should contain the raw file content to be written.
            """
            path = get_user_data_path(request)
            if not isinstance(path, str):
                return path

            overwrite = request.query.get("overwrite", 'true') != "false"
            full_info = request.query.get('full_info', 'false').lower() == "true"

            if not overwrite and os.path.exists(path):
                return web.Response(status=409, text="File already exists")

            try:
                body = await request.read()

                dir_name = os.path.dirname(path)
                fd, tmp_path = tempfile.mkstemp(dir=dir_name)
                try:
                    with os.fdopen(fd, "wb") as f:
                        f.write(body)
                    os.replace(tmp_path, path)
                except:
                    os.unlink(tmp_path)
                    raise
            except OSError as e:
                ...
                return web.Response(status=400, reason="Invalid filename. ...")

            user_path = self.get_request_user_filepath(request, None)
            if full_info:
                resp = get_file_info(path, user_path)
            else:
                resp = os.path.relpath(path, user_path)
            return web.json_response(resp)
```

`/api` プレフィックスは router が両対応（`server.py:1239-1248`）:

```python
        # Currently both the old endpoints without prefix and new endpoints with
        # prefix are supported.
        for route in self.routes:
            ...
            # routes to add /api prefix.
        self.app.add_routes(self.routes)
```

### 契約まとめ（**書き込みは実行していない**）

| 項目 | 値 |
|---|---|
| Method / Path | `POST /api/userdata/{file}`（`/userdata/{file}` も可） |
| `{file}` | URL エンコードされたユーザーディレクトリ相対パス。例 `workflows%2Fmy_wf.json`（`%` があると自動 unquote: `user_manager.py:88-91`） |
| Body | **生バイト列**（`await request.read()`）。JSON ラッパー無し、`Content-Type` 不問 |
| Query | `overwrite`（既定 `"true"`）/ `full_info`（既定 `"false"`） |
| 上書き | 既定で上書き。`tempfile.mkstemp` + `os.replace` によるアトミック置換。`overwrite=false` かつ既存 → `409 File already exists` |
| 親ディレクトリ | `get_request_user_filepath(..., create_dir=True)` が自動作成 |
| 成功時 | 200 + 相対パス文字列、または `full_info=true` で `{path,size,modified,created}` |
| 失敗 | 400（不正ファイル名）/ 403（パス不正・トラバーサル） |
| 認可 | 既定（非 multi_user）は user=`default`。`--multi-user` 時は `Comfy-User` ヘッダ必須 |

関連ルート（すべて `app/user_manager.py`）:
`GET /userdata`（150）/ `GET /v2/userdata`（214）/ `GET /userdata/{file}`（334）/ `DELETE /userdata/{file}`（427）/ `POST /userdata/{file}/move/{dest}`（437、`overwrite`・`full_info` 同じ）。

**重要な注意**: `workflows/.index.json` は**お気に入り専用**（`workflowStore.ts:759-799` の `useWorkflowBookmarkStore` が `{favorites: [...]}` を読み書きするだけ）。一覧はファイルシステム走査から作られるので、`.index.json` を更新しなくてもワークフローは一覧に出る。

**制限**: API 形式 JSON を `workflows/` に置いても、サイドバーから開くと `workflowService.openWorkflow`（`workflowService.ts:386-439`）→ `workflow.load()` → `app.loadGraphData()` 経路になり、**UI 形式（`nodes`/`links`）として解釈される**。`loadGraphData` は `graphData` が object であれば `defaultGraph` への差し替えをせず（`app.ts:1298-1305`）`rootGraph.configure(graphData)` に渡すため、API 形式では空/不正なグラフになる。API 形式は D&D / Open ボタン経由でないと正しく読まれない。
*未検証*: 実際の見え方（エラーダイアログの文言など）は実機確認していない。

---

## 4. 保存済みグラフの再実行（API 契約）

### 投入: `POST /prompt`（`server.py:1080-1152`）

```python
        @routes.post("/prompt")
        async def post_prompt(request):
            json_data =  await request.json()
            json_data = self.trigger_on_prompt(json_data)
            if "number" in json_data: number = float(json_data['number'])
            else:
                number = self.number
                if "front" in json_data:
                    if json_data['front']: number = -number
                self.number += 1
            if "prompt" in json_data:
                prompt = json_data["prompt"]
                client_prompt_id = json_data.get("prompt_id")
                if client_prompt_id is None: prompt_id = str(uuid.uuid4())
                else:
                    try: prompt_id = validate_job_id(client_prompt_id)
                    except ValueError: ... # 400 invalid_prompt_id
                partial_execution_targets = None
                if "partial_execution_targets" in json_data:
                    partial_execution_targets = json_data["partial_execution_targets"]
                self.node_replace_manager.apply_replacements(prompt)
                valid = await execution.validate_prompt(prompt_id, prompt, partial_execution_targets)
                extra_data = {}
                if "extra_data" in json_data: extra_data = json_data["extra_data"]
                if "client_id" in json_data: extra_data["client_id"] = json_data["client_id"]
                if "comfy_usage_source" not in extra_data:
                    usage_source = request.headers.get("Comfy-Usage-Source")
                    if usage_source: extra_data["comfy_usage_source"] = usage_source
                if valid[0]:
                    outputs_to_execute = valid[2]
                    sensitive = {}
                    for sensitive_val in execution.SENSITIVE_EXTRA_DATA_KEYS:
                        if sensitive_val in extra_data:
                            sensitive[sensitive_val] = extra_data.pop(sensitive_val)
                    extra_data["create_time"] = int(time.time() * 1000)
                    self.prompt_queue.put((number, prompt_id, prompt, extra_data, outputs_to_execute, sensitive))
                    response = {"prompt_id": prompt_id, "number": number, "node_errors": valid[3]}
                    return web.json_response(response)
                else:
                    return web.json_response({"error": valid[1], "node_errors": valid[3]}, status=400)
            else:
                error = {"type": "no_prompt", "message": "No prompt provided", ...}
                return web.json_response({"error": error, "node_errors": {}}, status=400)
```

- リクエスト: `{"prompt": <API graph>, "client_id": "<str>", "prompt_id": "<uuid, 任意>", "number": <int, 任意>, "front": <bool, 任意>, "extra_data": {...}, "partial_execution_targets": [...]}`
- レスポンス 200: `{"prompt_id": "...", "number": N, "node_errors": {...}}`
- レスポンス 400: `{"error": {...}|"str", "node_errors": {...}}`、`error.type` は `no_prompt` / `invalid_prompt_id` / validation エラー
- `extra_data["create_time"]` はサーバが付与。`client_id` は `extra_data` にコピーされる。

### 進捗・結果のポーリング

| 用途 | ルート | 備考 |
|---|---|---|
| 残キュー数 | `GET /prompt` | `{"exec_info": {"queue_remaining": N}}`（`server.py:755-757, 1291-1296`） |
| キュー中身 | `GET /queue` | `{"queue_running": [...], "queue_pending": [...]}`、機微情報除去済み（`server.py:1072-1078`） |
| 履歴（全件） | `GET /history?max_items=&offset=` | `server.py:1053-1065` |
| 履歴（1件） | `GET /history/{prompt_id}` | `server.py:1067-1070`。無ければ `{}` |
| ジョブ（新API） | `GET /api/jobs?status=&workflow_id=&sort_by=&sort_order=&limit=&offset=` | `server.py:829-925` |
| ジョブ（1件） | `GET /api/jobs/{job_id}` | `server.py:927-950`。**job_id == prompt_id** |
| 画像取得 | `GET /view?filename=&subfolder=&type=output` | `server.py:519-` |
| キャンセル | `POST /interrupt`（`{"prompt_id": ...}` で個別） / `POST /api/jobs/{job_id}/cancel` | `server.py:1168-1198, 979` |
| 履歴削除 | `POST /history {"clear":true}` / `{"delete":[ids]}` | `server.py:1211-1222` |
| 実時間 | `WS /ws`（`client_id` を `POST /prompt` に渡す） | `executing` / `progress` / `executed` / `status` イベント |

### seed / ウィジェット値のサーバ側上書き

**API には存在しない。クライアントがグラフ JSON を書き換えて送る必要がある。**

根拠:

- `control_after_generate` は `INPUT_TYPES` のメタデータ宣言のみ。例 `nodes.py:1611`:
  `"seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True, ...})`
  実際の increment / decrement / randomize はフロントエンドが実行する（サーバ側に該当処理は無い）。
- サーバがプロンプトを書き換えるのは 2 箇所だけ:
  - `self.node_replace_manager.apply_replacements(prompt)`（`server.py:1118`）— ノード**型**の置換（deprecated → replacement）でありウィジェット値の上書きではない
  - `trigger_on_prompt()` フック（`server.py:1464-1475`、`add_on_prompt_handler` で登録される拡張点）
- したがって再現ツールは `prompt["<node_id>"]["inputs"]["seed"] = <value>` のように自分で書き換える。

---

## 5. `GET /history` の形（実測）

`GET /history` → `{"<prompt_id>": entry, ...}`（実測 419 件）。`GET /history/{prompt_id}` → `{"<prompt_id>": entry}`。

### entry のトップレベルキー

実測 419 件すべて同一で **`meta`, `outputs`, `prompt`, `status`** の 4 つ。

**このバージョンでは `extra_data` は独立キーではなく、`prompt` のタプル要素として入る。**（`execution.py:1331-1351`）:

```python
    def task_done(self, item_id, history_result,
                  status: Optional['PromptQueue.ExecutionStatus'], process_item=None):
        with self.mutex:
            prompt = self.currently_running.pop(item_id)
            if len(self.history) > MAXIMUM_HISTORY_SIZE:
                self.history.pop(next(iter(self.history)))
            status_dict: Optional[dict] = None
            if status is not None:
                status_dict = copy.deepcopy(status._asdict())
            if process_item is not None:
                prompt = process_item(prompt)
            self.history[prompt[1]] = {
                "prompt": prompt,
                "outputs": {},
                'status': status_dict,
            }
            self.history[prompt[1]].update(history_result)
```

`history_result` は `execution.py:826-834`:

```python
                ui_outputs = {}
                meta_outputs = {}
                for node_id, ui_info in ui_node_outputs.items():
                    ui_outputs[node_id] = ui_info["output"]
                    meta_outputs[node_id] = ui_info["meta"]
                self.history_result = {
                    "outputs": ui_outputs,
                    "meta": meta_outputs,
                }
```

### 入れ子の形

```
{
  "<prompt_id>": {
    "prompt": [                     # 長さ5のリスト = queue item tuple そのまま
        0,                          # [0] number (int, 優先度)
        "<prompt_id>",              # [1] prompt_id
        { "1": {"class_type": "...", "inputs": {...}}, ... },   # [2] API graph
        { "client_id": "...", "create_time": ..., "extra_pnginfo": {...} },  # [3] extra_data
        ["9"]                       # [4] outputs_to_execute
    ],
    "outputs": {
      "9": { "images": [ { "filename": "naedoko_00132_.png", "subfolder": "", "type": "output" } ] }
    },
    "status": {
      "status_str": "success",      # or "error"
      "completed": true,
      "messages": [
        ["execution_start", {"prompt_id": "...", "timestamp": 1791865628675}],
        ["execution_cached", {"nodes": [], "prompt_id": "...", "timestamp": 1791865628728}],
        ["execution_success", {"prompt_id": "...", "timestamp": 1791865653870}]
      ]
    },
    "meta": {
      "9": {"node_id": "9", "display_node": "9", "parent_node": null, "real_node_id": "9"}
    }
  }
}
```

`meta` の生成元は `execution.py:567-572`:
```python
            meta = {
                "node_id": unique_id,
                "display_node": display_node_id,
                "parent_node": parent_node_id,
                "real_node_id": real_node_id,
            }
```

### 実測で確認した内容

- `prompt` の値は **419 件すべて list**（dict ではない）。
- `outputs` のキー集合（全 419 件を走査）:
  - `('images',)` — 417 件。例 `{"filename": "naedoko_00132_.png", "subfolder": "", "type": "output"}`
  - `('text',)` — 146 件。例（`PreviewAny` ノード, node "11"）:
    `{"text": ["Assistant\n- The character's eyes are in a relaxed, half-mast for the moment.\n..."]}`
    対応する `prompt[2]["11"]` は `{"inputs": {"source": ["9", 0]}, "class_type": "PreviewAny", "_meta": {"title": "なんでも表示（Show Any）"}}`
- `outputs` の `images[].filename` / `.subfolder` / `.type` は存在する（`type` は `"output"`）。
- `extra_data`（= `prompt[3]`）のキー集合（全 419 件を走査）:
  - `('client_id', 'create_time')` — 269 件（**API 起点**。`extra_pnginfo` 無し）
  - `('client_id', 'comfy_usage_source', 'create_time', 'extra_pnginfo')` — 150 件（**UI 起点**）
- `extra_pnginfo` のキーは `['workflow']` のみで、値は **完全な UI workflow**。実測例（`prompt_id=9d027971-f278-4538-ac87-b6547a9a3275`）:

```json
{"id": "8d01125b-023d-48b3-a23a-18ba2a6a6291", "revision": 0,
 "last_node_id": 9, "last_link_id": 28,
 "nodes": [{"id": 1, "type": "UNETLoader", "pos": [100, 130], "size": [270, 82],
            "flags": {}, "order": 0, "mode": 0, "inputs": [],
            "outputs": [{"name": "MODEL", "type": "MODEL", "links": [24]}],
            "properties": {"cnr_id": "comfy-core", "ver": "0.39.2", "Node name for S&R": "UNETLoader"},
            "widgets_values": ["anima-turbo-v1.1.safetensors", "default"],
            "widgets_values_named": {"unet_name": "anima-turbo-v1.1.safetensors", "weight_dtype": "default"}},
           ...],
 "links": [...], "groups": [], "config": {}, "extra": {}, "version": 0.4}
```

UI workflow のトップレベルキー: `config, extra, groups, id, last_link_id, last_node_id, links, nodes, revision, version`（`version` = 0.4）。

**→ UI 起点の実行であれば、`prompt[3].extra_pnginfo.workflow` から UI workflow がそのまま取得できる。API 起点では存在しない。**

- 「実行時に解決されたノードの値」について: 残るのは**ノード自身の出力**（`outputs[node].images` / `.text`）であり、入力ウィジェットの解決後値ではない。中間ノードの値は保存されない（UI 出力を持つノードのみ）。

### 別解: `GET /api/jobs/{prompt_id}`（より扱いやすい）

`comfy_execution/jobs.py:261-267`:

```python
    if include_outputs:
        job['outputs'] = normalize_outputs(outputs)
        job['execution_status'] = status_info
        job['workflow'] = {
            'prompt': prompt,
            'extra_data': extra_data,
        }
```

実測 `GET /api/jobs/62aa51ae-4d9e-4c88-807d-1d91bfba1f3d`:
トップレベルキー = `['create_time', 'execution_end_time', 'execution_start_time', 'execution_status', 'id', 'outputs', 'outputs_count', 'preview_output', 'previewable_outputs_count', 'priority', 'status', 'workflow', 'workflow_id']`

- `workflow.prompt` = API graph
- `workflow.extra_data.extra_pnginfo.workflow` = UI workflow（実測 17 ノード、`version: 0.4`）
- `outputs` = history と同じ形（`{"11": {"text": [...]}}`）
- `workflow_id` = UI workflow の `id`（`jobs.py:130-139`: `extra_pnginfo.get('workflow', {}).get('id')`）。**prompt_id ではない。**
- `job id` は **prompt_id と同じ**（`/history` のキーに存在することを確認）。`/api/jobs/{job_id}` に `/history/{prompt_id}` の id をそのまま渡せる。
- `preview_output` は `{"filename":..., "subfolder":..., "type":"output", "nodeId":"17", "mediaType":"images"}`

---

## 6. モデル / LoRA の同一性

### (a) モデルファイルのハッシュ記録 — **無い**

ComfyUI コアはモデルファイルのハッシュを記録も公開もしていない。

- `folder_paths.py` にハッシュ関連コードは一切無い（`get_filename_list` はファイル名のみ、`recursive_search` は `mtime` のみ）。
- `server.py` に `model_hash` / `sha256` / `hashlib` は無い。
- `comfy/k_diffusion/utils.py:37-48`: `download_file()` がダウンロード検証時にのみ `hashlib.sha256` を計算する（保存しない）:
  ```python
  def download_file(path, url, digest=None):
      """Downloads a file if it does not exist, optionally checking its SHA-256 hash."""
      ...
      if digest is not None:
          file_digest = hashlib.sha256(open(path, 'rb').read()).hexdigest()
          if digest != file_digest:
              raise OSError(f'hash of {path} (url: {url}) failed to validate')
  ```
- `node_helpers.py:68-75`:
  ```python
  def hasher():
      hashfuncs = {"md5": hashlib.md5, "sha1": hashlib.sha1,
                   "sha256": hashlib.sha256, "sha512": hashlib.sha512}
      return hashfuncs[args.default_hashing_function]
  ```
  用途は `--default-hashing-function`（既定 sha256、`comfy/cli_args.py:190`）で、**保存画像の重複ファイル名／内容比較**。モデルではない。
- `app/assets/services/hashing.py` は **blake3** を計算するが、対象は**生成アセット（出力画像等）**で、DB 登録／`GET /view?filename=blake3:...` の解決用（`server.py:524-538`、`app/assets/api/routes.py`）。モデルは対象外。
- 唯一近いもの: safetensors ヘッダの `sshs_model_hash` / `source_hash` を `app/assets/services/metadata_extract.py:268` が読むが、これは**生成画像のメタデータ抽出**経路。
- 注意: `/view?filename=blake3:...` の解決は `self.asset_manager.enabled` が真のときのみ有効（`server.py:528-530`）。

**→ 忠実再現のために (name, size, mtime) を記録するか、自前でフルハッシュを計算する必要がある。**

### (b) モデル一覧 API

| ルート | 返すもの | 定義 |
|---|---|---|
| `GET /experiment/models` | `[{"name": <folder>, "folders": [絶対パス...], "extensions": [...]}]`（`configs`/`custom_nodes` は除外） | `app/model_manager.py:30-43` |
| `GET /experiment/models/{folder}` | `[{"name": <相対パス>, "pathIndex": N, "modified": <float 秒>, "created": <float 秒>, "size": <bytes>}]` | `app/model_manager.py:46-52`, `138-184` |
| `GET /models` | フォルダ名（キー）の配列のみ | `server.py:345-349` |
| `GET /models/{folder}` | ファイル名（相対パス）の配列のみ。**size/mtime 無し** | `server.py:351-357` |
| `GET /object_info/{node}` の combo values | ファイル名（相対パス）のみ。**size/mtime/hash 無し** | `server.py:759-806`、`folder_paths.get_filename_list()` |

`/experiment/models` は実験的 API（`model_manager.py:29` のコメント `# NOTE: This is an experiment to replace /models`）。

`map_legacy` によるフォルダ統合（`folder_paths.py:111-`）で **`unet` は `diffusion_models` に、`clip` は `text_encoders` に統合**されているため、`/experiment/models/unet` と `/experiment/models/clip` は **404**。代わりに:

- `/experiment/models/diffusion_models` の `folders` = `['...\models\unet', '...\models\diffusion_models', '...\output\diffusion_models']`
  → `pathIndex=1` のエントリが `models\unet` → 実測では `pathIndex` 0 のファイルは無し（`models\unet` は空）
- `/experiment/models/text_encoders` の `folders` = `['...\models\text_encoders', '...\models\clip', '...\output\clip']`
  → `pathIndex=1` は `models\clip` → 実測では空

`GET /object_info/UNETLoader` 実測:

```json
{"UNETLoader": {"input": {"required": {
   "unet_name": [["NoctQ_V4_int8_convrot.safetensors", "anima-aesthetic-v1.1.safetensors",
                  "anima-base-v1.0.safetensors", "anima-turbo-v1.1.safetensors",
                  "waiANIMA_v10Base10.safetensors"]],
   "weight_dtype": [["default","fp8_e4m3fn","fp8_e4m3fn_fast","fp8_e5m2"], {"advanced": true}]}},
 "python_module": "nodes", ...}}
```

`GET /object_info/LoraLoaderModelOnly` 実測の `lora_name`:
`["BuAnime_NSFW_Style_Anima_BuAnimeV2.safetensors", "U149ALL_pony_v1beta.safetensors", "anima-incontext-character.safetensors", "cglora_test.safetensors", "gen_furaipan\\gen_furaipan_v1.safetensors", "gen_furaipan_anima.safetensors", "gen_ildcat\\gen_ildcat_v1.safetensors", "lsgirl2.safetensors", "tachibanaarisu_pony_v1.safetensors"]`

→ **サブフォルダを含む相対パス（`\` 区切り）が combo 値**。サイズ・ハッシュは取れない。

### (c) ディスク実測（ローカル時刻 = UTC+9、サイズはバイト）

`GET /experiment/models/{folder}` の `modified` は epoch 秒（float）。以下は `Get-ChildItem` の実測と一致する。

#### `models\diffusion_models`（6 エントリ / 23,985,697,984 bytes、うちダミー1）

| ファイル | bytes | mtime |
|---|---:|---|
| `anima-aesthetic-v1.1.safetensors` | 4,182,230,656 | 2026-10-03 00:27:47 |
| `anima-base-v1.0.safetensors` | 4,182,218,328 | 2026-10-02 23:24:39 |
| `anima-turbo-v1.1.safetensors` | 4,182,230,656 | 2026-10-03 00:31:15 |
| `NoctQ_V4_int8_convrot.safetensors` | 7,256,784,368 | 2026-10-09 22:07:10 |
| `waiANIMA_v10Base10.safetensors` | 4,182,233,976 | 2026-10-04 11:03:14 |
| `put_diffusion_model_files_here`（ダミー） | 0 | 2026-09-21 00:34:37 |

#### `models\unet`（空）

`put_unet_files_here`（0 bytes）のみ。

#### `models\text_encoders`（6 エントリ / 27,636,985,004 bytes、うちダミー1）

| ファイル | bytes | mtime |
|---|---:|---|
| `qwen_3_06b_base.safetensors` | 1,192,135,096 | 2026-10-02 23:25:37 |
| `qwen3vl_8b_int8_convrot.safetensors` | 9,350,798,360 | 2026-10-09 08:39:03 |
| `qwen3-vl-4b-heretic_int4.safetensors` | 2,814,749,472 | 2026-10-13 10:22:00 |
| `qwen3-vl-4b-heretic_int8.safetensors` | 4,836,949,032 | 2026-10-13 10:40:05 |
| `qwen3VL8BHereticINT8W4A8_int8.safetensors` | 9,442,353,044 | 2026-10-10 12:44:36 |
| `put_text_encoder_files_here`（ダミー） | 0 | 2026-09-21 00:34:37 |

#### `models\clip`（空）

`put_clip_or_text_encoder_models_here`（0 bytes）のみ。

#### `models\vae`（3 エントリ / 929,315,934 bytes、うちダミー1）

| ファイル | bytes | mtime |
|---|---:|---|
| `qwen_image_2.1_vae_bf16.safetensors` | 675,509,688 | 2026-10-09 08:26:32 |
| `qwen_image_vae.safetensors` | 253,806,246 | 2026-10-02 23:25:51 |
| `put_vae_here`（ダミー） | 0 | 2026-09-21 00:34:37 |

#### `models\loras`（10 エントリ / 1,690,198,288 bytes、うちダミー1）

| ファイル | bytes | mtime |
|---|---:|---|
| `anima-incontext-character.safetensors` | 554,343,064 | 2026-10-03 09:15:36 |
| `BuAnime_NSFW_Style_Anima_BuAnimeV2.safetensors` | 138,758,584 | 2026-10-10 00:06:57 |
| `cglora_test.safetensors` | 114,431,760 | 2026-09-29 10:40:59 |
| `gen_furaipan_anima.safetensors` | 132,365,656 | 2026-10-04 16:01:33 |
| `gen_furaipan\gen_furaipan_v1.safetensors` | 170,559,996 | 2026-09-28 04:30:37 |
| `gen_ildcat\gen_ildcat_v1.safetensors` | 170,562,788 | 2026-09-27 20:32:27 |
| `lsgirl2.safetensors` | 66,238,800 | 2026-10-04 03:08:52 |
| `tachibanaarisu_pony_v1.safetensors` | 228,457,788 | 2026-09-29 22:28:49 |
| `U149ALL_pony_v1beta.safetensors` | 114,479,852 | 2026-09-29 22:32:18 |
| `put_loras_here`（ダミー） | 0 | 2026-09-21 00:34:37 |

**SHA-256 実測（小さい 2 ファイルのみ。それ以外は未計算）:**

```
models\loras\lsgirl2.safetensors
  size=66,238,800  mtime=2026-10-04 03:08:52
  sha256=03BD85E28DADABC691712038B68AA7A09C6CEF5518B12697E33CB03EBB89C950

models\loras\cglora_test.safetensors
  size=114,431,760  mtime=2026-09-29 10:40:59
  sha256=2567A1F05FE8378494764459A84E57E0BF5289F124BBB5B29DD13DB050853536
```

4 GB 超の `diffusion_models` / `text_encoders` はハッシュ未計算（*未検証*）。

**再現レコードに推奨する識別子**: `(folder, name, size, mtime_epoch_sec)` を `GET /experiment/models/{folder}` から取得して記録。フルハッシュが必要なら自前で計算するしかない（API には無い）。

---

## 7. カスタムノードの同一性

### ComfyUI コア

カスタムノードのバージョン／コミットを返すルートは**無い**。

- `app/custom_node_manager.py` が公開するルートは `GET /workflow_templates`（96）と `GET /i18n`（140）のみ。
- ノード → モジュールの対応は `/object_info/{node}` の `python_module` で辿れる（`server.py:773`）:
  ```python
  info['python_module'] = getattr(obj_class, "RELATIVE_PYTHON_MODULE", "nodes")
  ```
  実測 `UNETLoader.python_module = "nodes"`（コアノード）。
- `/api/extensions` はフロントエンド拡張 JS のパス一覧のみ。

### ComfyUI-Manager（インストール済み）

`custom_nodes/comfyui-manager`（`pyproject.toml` version `3.42`、git `9c29dc68a488fd56e15f152807579009d627bfef`）。

`GET /api/customnode/installed` の**実測レスポンス**:

```json
{
  "comfyui-impact-pack":    {"ver": "8.28.3",                              "cnr_id": "comfyui-impact-pack",    "aux_id": null,                                     "enabled": true},
  "comfyui-impact-subpack": {"ver": "1.3.5",                               "cnr_id": "comfyui-impact-subpack", "aux_id": null,                                     "enabled": true},
  "comfyui-manager":        {"ver": "9c29dc68a488fd56e15f152807579009d627bfef", "cnr_id": "comfyui-manager",    "aux_id": "ltdrdata/ComfyUI-Manager",               "enabled": true},
  "ComfyUI-WD14-Tagger":    {"ver": "9e0a6e700299182fc05c58b62e7ad9f72182a78b", "cnr_id": "comfyui-wd14-tagger", "aux_id": "pythongosssss/ComfyUI-WD14-Tagger",     "enabled": true},
  "comfyui_ipadapter_plus": {"ver": "2.0.0",                               "cnr_id": "comfyui_ipadapter_plus", "aux_id": null,                                     "enabled": true}
}
```

- **git 管理のノードは `ver` がコミットハッシュ**（`comfyui-manager`, `ComfyUI-WD14-Tagger`）
- cnr 登録済みのノードは `ver` がバージョン番号
- `GET /api/manager/version` → 生テキスト `V3.42`
- 他ルート（`custom_nodes/comfyui-manager/glob/manager_server.py`）: `/customnode/getlist`(1057), `/customnode/getmappings`(785), `/customnode/versions/{node_name}`(1376), `/customnode/disabled_versions/{node_name}`(1387), `/snapshot/getlist`(1183), `/snapshot/get_current`(1253), `/manager/queue/status`(1435), `/manager/db_mode`(1801, 実測 `"cache"`)
- オフライン DB: `custom_nodes/comfyui-manager/custom-node-list.json` = **3,110,870 bytes**。これは**配布可能ノードのカタログ**であり、インストール済み一覧ではない。キャッシュは `user/__manager/cache/881334633_nodes.json` = 12,458,070 bytes。

### `.git/HEAD` 実測

| 対象 | 値 |
|---|---|
| `custom_nodes/comfyui-manager/.git/refs/heads/main` | `9c29dc68a488fd56e15f152807579009d627bfef` |
| `custom_nodes/ComfyUI-WD14-Tagger/.git/refs/heads/main` | `9e0a6e700299182fc05c58b62e7ad9f72182a78b` |
| `ComfyUI/.git/HEAD` | `3c1b7a17fdf239d35ce98cc777756f572d089795`（detached） |
| `ComfyUI/.git/refs/heads/master` | `08ff3c11b3a85eb07c2c06f21cb378ac2e086840` |
| `ComfyUI/.git/refs/heads/backup_branch_2026-10-10_03_13_29` | `73c9bad4d21e7addbe1d13bc92eee0f1431b017d` |
| `comfyui-anima-incontext` | `.git` 無し |
| `comfyui-impact-pack` / `comfyui-impact-subpack` / `comfyui_ipadapter_plus` | `.git` 無し |
| `illust_tagger` | **ジャンクション** → `C:\work\illust-packs\backend-comfyui-anima\comfy_nodes\illust_tagger` |

`custom_nodes/` 実測一覧: `comfyui-anima-incontext`, `comfyui-impact-pack`, `comfyui-impact-subpack`, `comfyui-manager`, `ComfyUI-WD14-Tagger`, `comfyui_ipadapter_plus`, `illust_tagger`(junction)。

### 重要なギャップ

`/api/customnode/installed` に **`comfyui-anima-incontext`（Anima の in-context 用ノード）と `illust_tagger` が出てこない**。追跡情報が無いため:

- `comfyui-anima-incontext`: `pyproject.toml` も `__version__` も無い（ファイルは `incontext.py` 13,783B / `incontext.py.bak` 13,069B / `nodes.py` 6,782B / `README.md` 7,125B / `style_adapter.py` 7,627B / `style_nodes.py` 6,881B / `__init__.py` 544B）。**バージョン識別子が存在しない。**
- `illust_tagger`: ワークスペース外（`C:\work\illust-packs\...`）へのジャンクションのため Manager が追跡していない。

**→ 忠実再現レコードには、`custom_nodes/` 直下の列挙 + 各ディレクトリの (git commit | pyproject version | `__init__.py` の mtime/size) を自前で記録する必要がある。**

その他のバージョン実測（`pyproject.toml` から）: `comfyui-impact-pack 8.28.3` / `comfyui-impact-subpack 1.3.5` / `comfyui-manager 3.42` / `ComfyUI-WD14-Tagger 1.0.1` / `comfyui_ipadapter_plus 2.0.0`。

実行環境（`GET /system_stats` 実測）:

```
comfyui_version = 0.39.2
required_frontend_version / comfyui-frontend-package = 1.53.10
comfyui-workflow-templates = 0.11.78, comfyui-embedded-docs = 0.5.13,
comfy-kitchen = 0.2.37, comfy-aimdo = 0.5.5
python 3.13.14, pytorch 2.13.0+cu130, embedded_python = true
deploy_environment = "local-portable"
argv = ["ComfyUI\\main.py", "--windows-standalone-build", "--port", "8188"]
devices = cuda:0 NVIDIA GeForce RTX 3060 (vram_total 12,884,377,600)
```

---

## 再現方法の選択肢（レビューツール向けランキング）

### A. `GET /api/jobs/{prompt_id}` から **UI workflow** を取り出してユーザーに D&D させる ★最有力

- **必要なもの**: `job.workflow.extra_data.extra_pnginfo.workflow`（または `/history/{prompt_id}` の `prompt[3].extra_pnginfo.workflow`）。`job_id == prompt_id` なので 1 リクエストで API graph・UI workflow・outputs・execution_status が全部取れる。
- **満たすべき条件**: その実行が **UI 起点**であること（実測 419 件中 **150 件**のみ。API 起点 269 件には `extra_pnginfo` が無い）。
- **失敗モード**:
  - `extra_pnginfo` が無い（API 起点）→ UI workflow が取得できない。B にフォールバック。
  - UI workflow のノード/リンクが現在のフロントエンドで解釈できない（`version: 0.4` の古い形式など）→ 欠落ノード警告。
  - カスタムノード未インストール → missing node プレースホルダ。
- **利点**: ノード位置・グループ・リンクが完全に復元される。ユーザーは D&D だけで開ける（`app.ts` の `drop` → `handleFile` → `workflow` 優先経路）。

### B. **API 形式 JSON** を書き出して D&D / Open させる（`loadApiJson` 経路）★次点・常に可能

- **必要なもの**: `{"<id>": {"class_type": "...", "inputs": {...}}, ...}` 形式。**全エントリが `class_type: string` を持ち `inputs` が object** であること（`isApiJson` の `every`。1 つでも欠けると弾かれる）。
- **満たすべき条件**: 常に可能（`/history/{id}` の `prompt[2]`、`/api/jobs/{id}` の `workflow.prompt`）。PNG の `prompt` チャンクでも同じ。
- **失敗モード**:
  - ノード位置・グループ情報が無いため `app.rootGraph.arrange()` による自動レイアウトになる。
  - カスタムノード未インストール → 読み込みは成功するが missing node プレースホルダ。
  - `_meta.title` が無いとタイトルが `class_type` の生値になる。
  - 空オブジェクトや非オブジェクト要素が混ざると `showErrorOnFileLoad` で弾かれる。
- **利点**: UI 起点 / API 起点を問わず常に使える。`prompt` チャンク付き PNG をそのまま渡すのと同じ経路。

### C. API 形式のまま `POST /prompt` で再生成 ★自動化向け

- **必要なもの**: `POST /prompt` に `{"prompt": <API graph>, "client_id": "<uuid>"}`。seed 変更は**クライアントが `inputs.seed` を書き換える**（サーバ側に上書き機能は無い）。
- **進捗**: `GET /prompt`（`exec_info.queue_remaining`）をポーリング、または `WS /ws` + `client_id`。
- **結果**: `GET /history/{prompt_id}` → `outputs[node].images[]` → `GET /view?filename=&subfolder=&type=output`。
- **失敗モード**:
  - モデルファイル名が変わっていると 400（`error` + `node_errors` に詳細）。**ファイル名のみが同一性の根拠**なので、同名・別内容のモデルを区別できない。
  - カスタムノード欠落で validation エラー → 400。
  - 生成実行が発生する（読み取り専用調査では実行していない）。
  - `extra_pnginfo` を送らないと、次回その履歴から UI workflow が取れなくなる（自己言及的に A が使えなくなる）。**UI workflow を `extra_data.extra_pnginfo.workflow` に同梱して送るのが望ましい。**

### D. `POST /api/userdata/workflows%2F<name>.json` で保存し、サイドバーから開かせる

- **必要なもの**: raw body に **UI 形式** JSON。`?overwrite=true`（既定）で上書き、`overwrite=false` なら既存時 409。親ディレクトリは自動作成。
- **失敗モード**:
  - **API 形式を保存すると開けない**（サイドバーは `workflowService.openWorkflow` → `app.loadGraphData()` 経路で UI 形式を前提とするため）。A か B で UI 形式に変換してから保存する必要がある。
  - 同名ファイルを既定で上書きしてしまう（ユーザーの既存ワークフローを破壊しうる）→ `overwrite=false` を推奨。
  - ユーザー操作が 1 ステップ増える（サイドバーから選択）。
  - `workflows/.index.json` はお気に入り専用なので更新不要だが、更新しても一覧には影響しない。
- **利点**: D&D 不要。ユーザーのワークフロー一覧に残る。パスを `GET /api/userdata?dir=workflows` で検証できる。

### E. `?template=` / `?share=` による URL ディープリンク — **再現ツールの手段としては使えない**

- `?template=<id>&source=default` は `/templates/<id>.json`（同梱テンプレート）のみ。`source=<module>` はカスタムノードの `example_workflows`。
- **`user/default/workflows/` のファイルを URL で開く手段は存在しない**（`?workflow=` は実装されていない。`PRESERVED_QUERY_NAMESPACES` に WORKFLOW 名前空間が無い）。
- `/api/userdata/workflows%2F<name>.json` を URL パラメータ経由で自動 fetch する仕組みも無い。加えて `GET /userdata/{file}` は `Content-Disposition: attachment` を返すため、URL を開いてもロードされない。
- `?share=` は Comfy のシェア機能前提（ローカル動作は*未検証*）。

---

## 未検証項目

- 実ブラウザでの D&D / Open ボタン動作（すべてソースコード上の確認）
- API 形式 JSON を `workflows/` に置いてサイドバーから開いた場合の実際の失敗の見え方（エラーダイアログ文言など）
- `?share=` のローカル環境での動作
- 4 GB 超モデルファイルの SHA-256
- `comfyui-anima-incontext` / `illust_tagger` の正確なバージョン（識別子が存在しないため）
- `/api/customnode/installed` に載らないノードが実際の生成に寄与しているか（ワークフロー内のノード型からは `python_module` で追えるが、本調査では未確認）
