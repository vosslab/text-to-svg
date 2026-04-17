type SceneRequest = {
	prompt: string;
	model: string | null;
	seed: number;
	width: number;
	height: number;
};

type SceneDebug = {
	rawModelOutput?: string;
	retryModelOutput?: string;
	usedFallback?: boolean;
	normalizationNotes?: string[];
};

type SceneResponse = {
	scene: unknown;
	normalizedFromModel: boolean;
	warnings: string[];
	debug: SceneDebug;
	svg: string;
};

type SceneEditorStatus = {
	ok: boolean;
	message: string;
};

type Point = [number, number];

type Shape =
	| { type: "circle"; cx: number; cy: number; r: number; fill?: string; stroke?: string; strokeWidth?: number }
	| { type: "rect"; x: number; y: number; width: number; height: number; rx?: number; ry?: number; fill?: string; stroke?: string; strokeWidth?: number }
	| { type: "ellipse"; cx: number; cy: number; rx: number; ry: number; fill?: string; stroke?: string; strokeWidth?: number }
	| { type: "line"; x1: number; y1: number; x2: number; y2: number; fill?: string; stroke?: string; strokeWidth?: number }
	| { type: "polygon"; points: Point[]; fill?: string; stroke?: string; strokeWidth?: number }
	| { type: "polyline"; points: Point[]; fill?: string; stroke?: string; strokeWidth?: number }
	| { type: "star"; cx: number; cy: number; points: number; outerRadius: number; innerRadius: number; rotation?: number; fill?: string; stroke?: string; strokeWidth?: number }
	| { type: "group"; transform?: string; shapes: Shape[] };

type Scene = {
	canvas: { width: number; height: number; viewBox: [number, number, number, number] };
	style?: { mood?: string[]; symmetry?: string; density?: string; palette?: string; seed?: number };
	shapes: Shape[];
};

function main(): void {
	const prompt = document.querySelector<HTMLTextAreaElement>("#prompt");
	const model = document.querySelector<HTMLSelectElement>("#model");
	const seed = document.querySelector<HTMLInputElement>("#seed");
	const width = document.querySelector<HTMLInputElement>("#width");
	const height = document.querySelector<HTMLInputElement>("#height");
	const generateButton = document.querySelector<HTMLButtonElement>("#generate");
	const resetButton = document.querySelector<HTMLButtonElement>("#reset");
	const status = document.querySelector<HTMLPreElement>("#status");
	const sceneJson = document.querySelector<HTMLTextAreaElement>("#scene-json");
	const svgHost = document.querySelector<HTMLDivElement>("#svg-host");
	const fallbackBanner = document.querySelector<HTMLDivElement>("#fallback-banner");
	const rawOutput = document.querySelector<HTMLTextAreaElement>("#raw-output");
	const retryOutput = document.querySelector<HTMLTextAreaElement>("#retry-output");
	if (!prompt || !model || !seed || !width || !height || !generateButton || !resetButton || !status || !sceneJson || !svgHost || !fallbackBanner || !rawOutput || !retryOutput) {
		throw new Error("Missing app elements.");
	}
	let lastGeneratedScene = "";

	generateButton.addEventListener("click", async function handleGenerate() {
		status.textContent = "Generating...";
		fallbackBanner.hidden = true;
		const payload: SceneRequest = {
			prompt: prompt.value,
			model: model.value ? model.value : null,
			seed: Number(seed.value),
			width: Number(width.value),
			height: Number(height.value),
		};
		const response = await fetch("/api/generate", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		});
		if (!response.ok) {
			throw new Error(`Generate failed with ${response.status}`);
		}
		const data = (await response.json()) as SceneResponse;
		const scene = data.scene as Scene;
		lastGeneratedScene = JSON.stringify(scene, null, 2);
		sceneJson.value = lastGeneratedScene;
		renderSceneFromEditor(sceneJson, svgHost, status);
		// surface raw model output so the user can see what the model actually said
		rawOutput.value = data.debug.rawModelOutput ?? "";
		retryOutput.value = data.debug.retryModelOutput ?? "";
		// clearly flag fallback scenes so they are not mistaken for real output
		if (data.debug.usedFallback) {
			fallbackBanner.textContent = "Fallback scene - model output could not be parsed. See raw model output below.";
			fallbackBanner.hidden = false;
		}
		status.textContent = data.warnings.length ? data.warnings.join("\n") : "Ready";
	});

	sceneJson.addEventListener("input", function handleSceneEdit() {
		renderSceneFromEditor(sceneJson, svgHost, status);
	});

	resetButton.addEventListener("click", function handleReset() {
		if (!lastGeneratedScene) {
			return;
		}
		sceneJson.value = lastGeneratedScene;
		renderSceneFromEditor(sceneJson, svgHost, status);
	});

	void loadModels();
}

function renderSceneFromEditor(
	sceneJson: HTMLTextAreaElement,
	svgHost: HTMLDivElement,
	status: HTMLPreElement,
): SceneEditorStatus {
	try {
		const scene = JSON.parse(sceneJson.value) as Scene;
		const svg = sceneToSvg(scene);
		svgHost.innerHTML = svg;
		status.textContent = "Ready";
		return { ok: true, message: "Rendered" };
	} catch (error) {
		const message = error instanceof Error ? error.message : "Invalid scene JSON";
		status.textContent = message;
		return { ok: false, message };
	}
}

function sceneToSvg(scene: Scene): string {
	const width = scene.canvas.width;
	const height = scene.canvas.height;
	const viewBox = scene.canvas.viewBox.join(" ");
	const body = scene.shapes.map(shapeToSvg).join("");
	return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="${viewBox}">${body}</svg>`;
}

function shapeToSvg(shape: Shape): string {
	if (shape.type === "circle") {
		return `<circle cx="${shape.cx}" cy="${shape.cy}" r="${shape.r}" fill="${shape.fill ?? "none"}" stroke="${shape.stroke ?? "none"}" stroke-width="${shape.strokeWidth ?? 2}"/>`;
	}
	if (shape.type === "rect") {
		return `<rect x="${shape.x}" y="${shape.y}" width="${shape.width}" height="${shape.height}" rx="${shape.rx ?? 0}" ry="${shape.ry ?? 0}" fill="${shape.fill ?? "none"}" stroke="${shape.stroke ?? "none"}" stroke-width="${shape.strokeWidth ?? 2}"/>`;
	}
	if (shape.type === "ellipse") {
		return `<ellipse cx="${shape.cx}" cy="${shape.cy}" rx="${shape.rx}" ry="${shape.ry}" fill="${shape.fill ?? "none"}" stroke="${shape.stroke ?? "none"}" stroke-width="${shape.strokeWidth ?? 2}"/>`;
	}
	if (shape.type === "line") {
		return `<line x1="${shape.x1}" y1="${shape.y1}" x2="${shape.x2}" y2="${shape.y2}" fill="${shape.fill ?? "none"}" stroke="${shape.stroke ?? "none"}" stroke-width="${shape.strokeWidth ?? 2}"/>`;
	}
	if (shape.type === "polygon" || shape.type === "polyline") {
		const points = shape.points.map(point => `${point[0]},${point[1]}`).join(" ");
		const tag = shape.type;
		return `<${tag} points="${points}" fill="${shape.fill ?? "none"}" stroke="${shape.stroke ?? "none"}" stroke-width="${shape.strokeWidth ?? 2}"/>`;
	}
	if (shape.type === "star") {
		const points = starPoints(shape).map(point => `${point[0].toFixed(2)},${point[1].toFixed(2)}`).join(" ");
		return `<polygon points="${points}" fill="${shape.fill ?? "none"}" stroke="${shape.stroke ?? "none"}" stroke-width="${shape.strokeWidth ?? 2}"/>`;
	}
	if (shape.type === "group") {
		const inner = shape.shapes.map(shapeToSvg).join("");
		if (shape.transform) {
			return `<g transform="${shape.transform}">${inner}</g>`;
		}
		return `<g>${inner}</g>`;
	}
	return "";
}

function starPoints(shape: Extract<Shape, { type: "star" }>): Point[] {
	const points: Point[] = [];
	const total = shape.points * 2;
	for (let index = 0; index < total; index += 1) {
		const angle = (Math.PI * index) / shape.points + (shape.rotation ?? 0) * (Math.PI / 180);
		const radius = index % 2 === 0 ? shape.outerRadius : shape.innerRadius;
		const x = shape.cx + Math.cos(angle) * radius;
		const y = shape.cy + Math.sin(angle) * radius;
		points.push([x, y]);
	}
	return points;
}

async function loadModels(): Promise<void> {
	const model = document.querySelector<HTMLSelectElement>("#model");
	if (!model) {
		throw new Error("Missing model select element.");
	}
	const response = await fetch("/api/models");
	if (!response.ok) {
		model.innerHTML = '<option value="">apple foundation</option>';
		return;
	}
	const data = (await response.json()) as { models: string[] };
	const options: string[] = ['<option value="">apple foundation</option>'];
	for (const name of data.models) {
		options.push(`<option value="${name}">${name}</option>`);
	}
	model.innerHTML = options.join("");
}

main();
