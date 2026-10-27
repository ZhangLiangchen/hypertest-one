/** Updated only after the immutable release and both downloadable assets exist. */
export type CliRelease = { published: false } | {
  published: true;
  version: string;
  sourceCommit: string;
  releaseUrl: string;
  installerUrl: string;
  installerSha256: string;
  artifactUrl: string;
  artifactSha256: string;
};
export const CLI_RELEASE: CliRelease = {
  published: true,
  version: "0.1.1",
  sourceCommit: "01b6d1ebcd64326808771ed06ac1166b98cceb6c",
  releaseUrl: "https://github.com/ZhangLiangchen/hypertest-one/releases/tag/cli-v0.1.1",
  installerUrl: "https://github.com/ZhangLiangchen/hypertest-one/releases/download/cli-v0.1.1/install-cli-release.py",
  installerSha256: "20413d4dbfcbaa1f145e1502f85a62c8a00e4a8914ab8c0c1a1a9768a8f65c95",
  artifactUrl: "https://github.com/ZhangLiangchen/hypertest-one/releases/download/cli-v0.1.1/hypertest-cli-0.1.1.pyz",
  artifactSha256: "6b258850b14ece41a5489f995e3ca832ea673b575b4859b2649b5992444ad735",
};
const quote = (value: string) => `'${value.replace(/'/g, `'"'"'`)}'`;

/** Both files are downloaded first. Execute only installer bytes matching the pinned digest. */
export function cliInstallCommand(release: CliRelease = CLI_RELEASE): string | null {
  if (!release.published) return null;
  if (!/^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$/.test(release.version) || !/^[a-f0-9]{40}$/.test(release.sourceCommit)
    || ![release.installerSha256, release.artifactSha256].every((value) => /^[a-f0-9]{64}$/.test(value))) throw new Error("CLI_RELEASE_METADATA_INVALID");
  for (const address of [release.releaseUrl, release.installerUrl, release.artifactUrl]) {
    const url = new URL(address);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) throw new Error("CLI_RELEASE_METADATA_INVALID");
  }
  const installer = "install-cli-release.py", artifact = `hypertest-cli-${release.version}.pyz`;
  const source = [
    "import hashlib,pathlib,sys",
    'sys.version_info >= (3,12) or sys.exit("Python 3.12 or later is required")',
    `p=pathlib.Path(${JSON.stringify(installer)})`,
    "data=p.read_bytes()",
    `hashlib.sha256(data).hexdigest()==${JSON.stringify(release.installerSha256)} or sys.exit("Installer SHA-256 mismatch")`,
    `sys.argv=[str(p),"--artifact",${JSON.stringify(artifact)},"--sha256",${JSON.stringify(release.artifactSha256)},"--version",${JSON.stringify(release.version)}]`,
    'exec(compile(data,str(p),"exec"),{"__name__":"__main__","__file__":str(p)})',
  ].join(";");
  return `python3 -I -c ${quote(source)}`;
}
