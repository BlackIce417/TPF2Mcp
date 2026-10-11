import {cp, mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {defineConfig} from 'vite';

const PROJECT_ROOT = import.meta.dirname;
const SOURCE_ROOT = resolve(PROJECT_ROOT, 'src');
const PASSTHROUGH = ['templates'];

function copyHtmlTemplates() {
  return {
    name: 'copy-html-templates',
    apply: 'build',
    async closeBundle() {
      const destination = resolve(PROJECT_ROOT, 'dist');
      await mkdir(destination, {recursive: true});
      await Promise.all(PASSTHROUGH.map(name => cp(
        resolve(SOURCE_ROOT, name),
        resolve(destination, name),
        {recursive: true, force: true},
      )));
    },
  };
}

const apiTarget = process.env.TPF2_API_TARGET || 'http://127.0.0.1:8765';
const proxy = {
  '/api': {
    target: apiTarget,
    changeOrigin: false,
  },
};

export default defineConfig({
  root: SOURCE_ROOT,
  publicDir: resolve(PROJECT_ROOT, 'public'),
  plugins: [copyHtmlTemplates()],
  server: {proxy},
  preview: {proxy},
  build: {
    outDir: resolve(PROJECT_ROOT, 'dist'),
    emptyOutDir: true,
    rollupOptions: {
      input: {
        network: resolve(SOURCE_ROOT, 'index.html'),
        local: resolve(SOURCE_ROOT, 'local.html'),
        timetable: resolve(SOURCE_ROOT, 'timetable.html'),
        regions: resolve(SOURCE_ROOT, 'regions.html'),
      },
    },
  },
});
