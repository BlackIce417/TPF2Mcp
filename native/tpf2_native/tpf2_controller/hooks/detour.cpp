#include "pch.h"
#include "detour.h"


static BOOL is_readable_range(const void* address, SIZE_T length)
{
	MEMORY_BASIC_INFORMATION memory_info{};
	if (address == nullptr || length == 0 ||
		VirtualQuery(address, &memory_info, sizeof(memory_info)) == 0 ||
		memory_info.State != MEM_COMMIT ||
		(memory_info.Protect & (PAGE_NOACCESS | PAGE_GUARD))) {
		return FALSE;
	}

	const uintptr_t begin = reinterpret_cast<uintptr_t>(address);
	const uintptr_t region_begin = reinterpret_cast<uintptr_t>(memory_info.BaseAddress);
	if (begin < region_begin || begin - region_begin > memory_info.RegionSize) {
		return FALSE;
	}
	return length <= memory_info.RegionSize - (begin - region_begin);
}


DetourManager& DetourManager::Instance() {
    static DetourManager Instance;
    return Instance;
}

DetourManager::HookCallGuard::HookCallGuard(DetourManager& manager)
	: manager_(&manager)
{
}

DetourManager::HookCallGuard::~HookCallGuard()
{
	if (manager_ != nullptr) {
		manager_->leave_hook();
	}
}

DetourManager::HookCallGuard DetourManager::adopt_hook_call()
{
	return HookCallGuard(*this);
}

BOOL DetourManager::is_draining() const
{
	return state_.load(std::memory_order_acquire) == DetourState::Draining;
}

void DetourManager::leave_hook()
{
	uint32_t previous = active_calls_.fetch_sub(1, std::memory_order_acq_rel);
	if (previous == 1) {
		active_calls_.notify_all();
	}
}

void DetourManager::wait_for_hook_calls()
{
	for (;;) {
		uint32_t active = active_calls_.load(std::memory_order_acquire);
		if (active == 0) {
			return;
		}
		active_calls_.wait(active, std::memory_order_relaxed);
	}
}

int DetourManager::RegisterHook(UINT64* target, DWORD length) {
	if (target == nullptr) {
		OutputDebugStringA("DetourManager::RegisterHook: target is nullptr\n");
		return 3;
	}
	if (hookMap_.find(target) != hookMap_.end()) {
		OutputDebugStringA("DetourManager::RegisterHook: already registered\n");
		return 1;
	}
	struct HookTarget bp;
    bp.target = target;
    if (length) {
        bp.length = length;
    }
	std::unique_lock vec_lock(vec_hook_lock);
	std::unique_lock map_lock(map_hook_lock);
	hooks_.push_back(bp);
	hookMap_[target] = bp;
	return 0;
}

BOOL DetourManager::AllocateTrampolinePage(struct HookTarget& bp)
{
	std::unique_lock _vec_page_lock(vec_page_lock);
	for (int i = 0; i < trampolinePages_.size(); ++i) {
		TrampolinePage& page = trampolinePages_[i];
		if (page.left_size < page.block_size) {
            continue;
		}
		//Assume not block was freed. If a block was freed, we should check if the block is used or not, 
        // so bp.start_in_page should be calculated by the index of the block, not by used_blocks.
		bp.page = page.page_base;
        bp.start_in_page = page.used_blocks * page.block_size;
        page.used_blocks++;
        page.left_size -= page.block_size;
		return TRUE;
	}
	// If no suitable page was found, allocate a new one
	VOID* new_page = VirtualAlloc(NULL, 0x1000, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
	if (new_page == nullptr) {
		return FALSE;
	}
	struct TrampolinePage new_trampoline_page;
	new_trampoline_page.page_base = (UINT64*)new_page;
	new_trampoline_page.used_blocks = 1;
	new_trampoline_page.left_size -= new_trampoline_page.block_size;

	trampolinePages_.push_back(new_trampoline_page);
	bp.page = new_trampoline_page.page_base;
	bp.start_in_page = 0;

	std::unique_lock _map_page_lock(map_page_lock);
	trampolineMap_.clear();
	for (TrampolinePage& page : trampolinePages_) {
		trampolineMap_[page.page_base] = &page;
	}
	return TRUE;
}

int DetourManager::install_detour(unsigned char* target, const unsigned char* expected, SIZE_T length,
    void* hook, void** original, const char* failure)
{
	std::unique_lock manager_guard(lock_);
	if (target == nullptr || expected == nullptr || hook == nullptr || original == nullptr ||
		length < 14 || length > 18 || !is_readable_range(target, length) ||
		state_.load(std::memory_order_acquire) == DetourState::Draining) {
		OutputDebugStringA("DetourManager::install_detour: invalid arguments\n");
		return 0;
	}
	if (memcmp(target, expected, length) != 0) {
		OutputDebugStringA(failure != nullptr ? failure : "DetourManager::install_detour: signature mismatch\n");
		return 0;
	}

	*original = nullptr;
	if (RegisterHook((UINT64*)target, (DWORD)length) != 0) {
		OutputDebugStringA("DetourManager::install_detour: RegisterHook failed\n");
		return 0;
	}

	struct HookTarget bp = hookMap_[(UINT64*)target];
	auto remove_registration = [&]() {
		std::unique_lock vec_lock(vec_hook_lock);
		std::unique_lock map_lock(map_hook_lock);
		for (auto entry = hooks_.begin(); entry != hooks_.end(); ++entry) {
			if (entry->target == bp.target) {
				hooks_.erase(entry);
				break;
			}
		}
		hookMap_.erase(bp.target);
	};
	if (!AllocateTrampolinePage(bp))
	{
		OutputDebugStringA("DetourManager::install_detour: AllocateTrampolinePage failed\n");
		remove_registration();
		return 0;
	}
	auto* block = reinterpret_cast<unsigned char*>(bp.page) + bp.start_in_page;
	auto* gateway = block;
	auto* trampoline = block + 32;
	SIZE_T gateway_offset = 0;
	gateway[gateway_offset++] = 0x50;
	gateway[gateway_offset++] = 0x48;
	gateway[gateway_offset++] = 0xB8;
	*reinterpret_cast<uint64_t*>(gateway + gateway_offset) =
		reinterpret_cast<uint64_t>(&active_calls_);
	gateway_offset += sizeof(uint64_t);
	gateway[gateway_offset++] = 0xF0;
	gateway[gateway_offset++] = 0xFF;
	gateway[gateway_offset++] = 0x00;
	gateway[gateway_offset++] = 0x58;
	gateway[gateway_offset++] = 0xFF;
	gateway[gateway_offset++] = 0x25;
	*reinterpret_cast<uint32_t*>(gateway + gateway_offset) = 0;
	gateway_offset += sizeof(uint32_t);
	*reinterpret_cast<uint64_t*>(gateway + gateway_offset) = reinterpret_cast<uint64_t>(hook);
	gateway_offset += sizeof(uint64_t);
	while (gateway_offset < 32) {
		gateway[gateway_offset++] = 0x90;
	}

    memcpy(trampoline, bp.target, length);
	trampoline[length] = 0xFF;
	trampoline[length + 1] = 0x25;
    *(uint32_t*)(trampoline + length + 2) = 0;
    *(uint64_t*)(trampoline + length + 6) = (uint64_t)(target + length);
	FlushInstructionCache(GetCurrentProcess(), block, sizeof(TrampolineBlock));
    *original = trampoline;
	bp.original = (UINT64*)trampoline;
	bp.length = (DWORD)length;
	{
		std::unique_lock vec_lock(vec_hook_lock);
		std::unique_lock map_lock(map_hook_lock);
		for (HookTarget& hook_target : hooks_) {
			if (hook_target.target == bp.target) {
				hook_target = bp;
				break;
			}
		}
		hookMap_[bp.target] = bp;
	}
    DWORD old;
	if (!VirtualProtect(target, length, PAGE_EXECUTE_READWRITE, &old)) {
		*original = nullptr;
		remove_registration();
        return 0;
	}
	state_.store(DetourState::Active, std::memory_order_release);
    target[0] = 0xFF;
    target[1] = 0x25;
    *(uint32_t*)(target + 2) = 0;
	*(uint64_t*)(target + 6) = (uint64_t)gateway;
    for (SIZE_T i = 14; i < length; ++i)
        target[i] = 0x90;
    FlushInstructionCache(GetCurrentProcess(), target, length);
	DWORD ignored = 0;
	if (!VirtualProtect(target, length, old, &ignored)) {
		memcpy(target, trampoline, length);
		FlushInstructionCache(GetCurrentProcess(), target, length);
		VirtualProtect(target, length, old, &ignored);
		*original = nullptr;
		remove_registration();
		return 0;
	}
    return 1;
}

int DetourManager::uninstall_all_detours()
{
	std::unique_lock manager_guard(lock_);
	state_.store(DetourState::Draining, std::memory_order_release);
	int result = 1;
	std::unique_lock vec_hook_guard(vec_hook_lock);
	std::unique_lock map_hook_guard(map_hook_lock);

	for (auto hook = hooks_.rbegin(); hook != hooks_.rend(); ++hook) {
		if (hook->target == nullptr || hook->original == nullptr || hook->length == 0) {
			result = 0;
			continue;
		}

		DWORD old_protect = 0;
		if (!VirtualProtect(hook->target, hook->length, PAGE_EXECUTE_READWRITE, &old_protect)) {
			result = 0;
			continue;
		}

		memcpy(hook->target, hook->original, hook->length);
		FlushInstructionCache(GetCurrentProcess(), hook->target, hook->length);

		DWORD ignored = 0;
		if (!VirtualProtect(hook->target, hook->length, old_protect, &ignored)) {
			result = 0;
		}
	}
	if (!result) {
		return 0;
	}
	wait_for_hook_calls();

	hooks_.clear();
	hookMap_.clear();
	vec_hook_guard.unlock();
	map_hook_guard.unlock();

	std::unique_lock vec_page_guard(vec_page_lock);
	std::unique_lock map_page_guard(map_page_lock);
	std::vector<TrampolinePage> remaining_pages;
	for (const TrampolinePage& page : trampolinePages_) {
		if (page.page_base != nullptr && !VirtualFree(page.page_base, 0, MEM_RELEASE)) {
			result = 0;
			remaining_pages.push_back(page);
		}
	}
	trampolinePages_ = std::move(remaining_pages);
	trampolineMap_.clear();
	for (TrampolinePage& page : trampolinePages_) {
		trampolineMap_[page.page_base] = &page;
	}
	if (trampolinePages_.empty()) {
		state_.store(DetourState::Uninstalled, std::memory_order_release);
	}

	return result;
}

DetourManager::DetourManager() = default;
DetourManager::~DetourManager() = default;

