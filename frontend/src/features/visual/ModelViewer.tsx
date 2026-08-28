import { Canvas } from '@react-three/fiber';
import { OrbitControls, Environment, useGLTF } from '@react-three/drei';
import { Suspense, useRef } from 'react';
import * as THREE from 'three';

interface Props {
  modelUrl?: string;
  allowDemo?: boolean;
}

function Model({ url, allowDemo }: { url?: string; allowDemo: boolean }) {
  if ((!url || url.includes('/mock/')) && allowDemo) {
    return (
      <mesh rotation={[0, 0, 0]}>
        <dodecahedronGeometry args={[1.2, 0]} />
        <meshStandardMaterial color="#1a1a1a" metalness={0.8} roughness={0.4} wireframe={false} />
      </mesh>
    );
  }
  if (!url) return null;
  return <GLBModel url={url} />;
}

function GLBModel({ url }: { url: string }) {
  const { scene } = useGLTF(url) as { scene: THREE.Group };
  const ref = useRef<THREE.Group>(null);
  return <primitive ref={ref} object={scene} scale={1.5} />;
}

export function ModelViewer({ modelUrl, allowDemo = false }: Props) {
  return (
    <Canvas
      camera={{ position: [3, 2, 3], fov: 45 }}
      gl={{ antialias: true, alpha: false }}
      style={{ background: '#050505' }}
    >
      <ambientLight intensity={0.3} />
      <directionalLight position={[5, 5, 5]} intensity={0.8} color="#f2f2f2" />
      <directionalLight position={[-3, -2, -3]} intensity={0.2} color="#858585" />
      <Suspense fallback={null}>
        <Model url={modelUrl} allowDemo={allowDemo} />
        <Environment preset="studio" />
      </Suspense>
      <OrbitControls
        enablePan={false}
        minDistance={2}
        maxDistance={10}
        autoRotate={false}
        enableDamping
        dampingFactor={0.1}
      />
      {/* Grid */}
      <gridHelper args={[10, 20, '#1a1a1a', '#0d0d0d']} position={[0, -1.5, 0]} />
    </Canvas>
  );
}
