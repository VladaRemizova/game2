import {
  BackSide, CanvasTexture, Color, CubeCamera, DoubleSide, HalfFloatType, LinearFilter, Mesh,
  MeshBasicMaterial, PlaneGeometry, PMREMGenerator, Scene, ShaderMaterial,
  SphereGeometry, SRGBColorSpace, WebGLCubeRenderTarget, WebGLRenderer,
} from 'three';

type Card = {position: [number, number, number]; size: [number, number]; radiance: number};

// Radiance values are linear: large neutral reflectors surround the ring,
// while a few narrow negative-fill cards define the polished metal's edges.
export const brightStudioSettings = {
  metal: {
    surround: [0.34, 0.60, 0.80], blur: 0.004, roughnessMultiplier: 0.70,
    cards: [
      {position: [-4, 3, 4], size: [6, 8], radiance: 2.4},
      {position: [4, 1, 2], size: [4, 7], radiance: 2.0},
      {position: [0, 5, -1], size: [7, 6], radiance: 2.5},
      {position: [-3, 1, -4], size: [5, 7], radiance: 1.6},
      {position: [3, -2, -4], size: [5, 6], radiance: 1.6},
      {position: [0, -4, 2], size: [7, 6], radiance: 1.8},
      {position: [1, 1, 3.5], size: [1.3, 7], radiance: 0.002},
      {position: [-3.5, 0, 1], size: [0.9, 6], radiance: 0.003},
      {position: [2.5, 0, -3], size: [1.0, 7], radiance: 0.002},
    ] as Card[],
  },
  diamonds: {
    surround: [0.16, 0.26, 0.42], cubeSize: 512,
    cards: [
      {position: [-4, 4, 4], size: [5, 6], radiance: 4.0},
      {position: [4, 2, 3], size: [3, 6], radiance: 4.5},
      {position: [0, 5, -1], size: [6, 5], radiance: 4.0},
      {position: [-3, 0, -5], size: [4, 6], radiance: 3.0},
      {position: [3, -2, -4], size: [3, 5], radiance: 3.5},
      {position: [0, -5, 1], size: [6, 6], radiance: 2.5},
      {position: [1, 1, 3.5], size: [1.0, 7], radiance: 0.008},
      {position: [-3.5, 0, 1], size: [1.1, 6], radiance: 0.012},
      {position: [2.5, 0, -3], size: [1.0, 7], radiance: 0.008},
    ] as Card[],
  },
};

function room(settings: {surround: number[]; cards: Card[]}) {
  const scene = new Scene();
  const canvas = document.createElement('canvas');canvas.width = 512;canvas.height = 16;
  const context = canvas.getContext('2d')!;
  const gradient = context.createLinearGradient(0, 0, 512, 0);
  for (const [offset, color] of [[0, '#858585'], [0.2, '#eeeeee'], [0.48, '#ffffff'], [0.75, '#f4f4f4'], [1, '#aaaaaa']] as const) {
    gradient.addColorStop(offset, color);
  }
  context.fillStyle = gradient;context.fillRect(0, 0, 512, 16);
  const softbox = new CanvasTexture(canvas);softbox.colorSpace = SRGBColorSpace;
  scene.userData.softbox = softbox;
  scene.add(new Mesh(new SphereGeometry(20, 32, 16), new ShaderMaterial({
    side: BackSide, toneMapped: false,
    uniforms: {radiance: {value: settings.surround}},
    vertexShader: 'varying vec3 direction; void main(){direction=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
    fragmentShader: `varying vec3 direction; uniform float radiance[3];
      void main(){float y=normalize(direction).y;
        float v=mix(radiance[0],radiance[1],smoothstep(-0.2,0.9,y));
        v=mix(v,radiance[2],1.0-smoothstep(-0.9,-0.25,y));
        gl_FragColor=vec4(vec3(v),1.0);}`,
  })));
  for (const {position, size, radiance} of settings.cards) {
    const card = new Mesh(new PlaneGeometry(...size), new MeshBasicMaterial({
      color: new Color().setRGB(radiance, radiance, radiance), side: DoubleSide, toneMapped: false,
      map: radiance > 1 ? softbox : null,
    }));
    card.position.set(...position);card.lookAt(0, 0, 0);scene.add(card);
  }
  return scene;
}

export function createBrightEnvironment(renderer: WebGLRenderer, pmrem: PMREMGenerator) {
  const metalRoom = room(brightStudioSettings.metal);
  const metal = pmrem.fromScene(metalRoom, brightStudioSettings.metal.blur).texture;
  const diamondRoom = room(brightStudioSettings.diamonds);
  const diamondCube = new WebGLCubeRenderTarget(brightStudioSettings.diamonds.cubeSize, {
    type: HalfFloatType, minFilter: LinearFilter, magFilter: LinearFilter,
  });
  new CubeCamera(0.1, 100, diamondCube).update(renderer, diamondRoom);
  for (const scene of [metalRoom, diamondRoom]) {
    scene.traverse((object) => {
      if (object instanceof Mesh) {object.geometry.dispose();(object.material as MeshBasicMaterial).dispose();}
    });
    (scene.userData.softbox as CanvasTexture).dispose();
  }
  return {metal, diamonds: diamondCube.texture};
}
