EAPI=7
DESCRIPTION="Ebuild with uncheckable large amount of USE deps"
HOMEPAGE="https://github.com/pkgcore/pkgcheck"
LICENSE="BSD"
SLOT="0"

# This example is pulled out of dev-lang/rust:
# https://gitweb.gentoo.org/repo/gentoo.git/tree/dev-lang/rust/rust-1.62.1.ebuild?id=60de1a24bbd551cb852f54ebf2b1aa5620c2aa2c#n55
ALL_LLVM_TARGETS=( AArch64 AMDGPU ARM AVR BPF Hexagon Lanai Mips MSP430
	NVPTX PowerPC RISCV Sparc SystemZ WebAssembly X86 XCore )
ALL_LLVM_TARGETS=( "${ALL_LLVM_TARGETS[@]/#/llvm_targets_}" )
LLVM_TARGET_USEDEPS=${ALL_LLVM_TARGETS[@]/%/(-)?}

IUSE+="${ALL_LLVM_TARGETS[@]#-}"
LLVM_DEPEND="|| ( "
for _s in 13 14 15; do
	LLVM_DEPEND+=" ( "
	LLVM_DEPEND+=" stub/stable:${_s}[${LLVM_TARGET_USEDEPS// /,}]"
	LLVM_DEPEND+=" )"
done
LLVM_DEPEND+=" ) "
RDEPEND="${LLVM_DEPEND}"
